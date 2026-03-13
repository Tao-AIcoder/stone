# 默行者 (STONE)

自托管个人 AI 助手，以飞书为主要交互界面，本地 + 云端大模型路由。

---

## 架构概览

STONE 分为两层：**可替换层**（外部有成熟三方组件可换）和**核心层**（系统特有逻辑，不过度乐高化）。

```
┌─────────────────────────────────────────────────────────┐
│                    可替换层（乐高化）                      │
│                                                         │
│  Gateway  │  Memory  │  Auth  │  Sandbox  │  Scheduler  │
│  飞书/TG  │ SQLite/  │ 白名单/ │ Noop/     │ APSched/   │
│           │ Redis    │ OAuth  │ Docker    │ Celery      │
│                                                         │
│  ModelRouter  │  Audit  │  PromptGuard                  │
│  直连/LiteLLM │ SQLite/ │ 正则/                         │
│               │ ELK     │ LlamaGuard                    │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                    核心层（不可替换）                      │
│                                                         │
│   Agent  ──  StateMachine  ──  ContextManager           │
│                  │                                      │
│           DryRunManager  ──  SkillRegistry              │
└─────────────────────────────────────────────────────────┘
```

---

## 可替换层：如何换模块

所有可替换模块通过 `stone.config.json` 的 `driver` 字段控制，**无需修改任何业务代码**。

### 当前可替换模块

| 组件 | 接口文件 | 当前 driver | 可替换为 |
|------|----------|-------------|----------|
| **网关** (Gateway) | `modules/interfaces/gateway.py` | `feishu` | `telegram`、`wechat`（Phase 2）|
| **短期记忆** | `modules/interfaces/memory.py` | `inmemory` | `redis`（Phase 2）|
| **长期存储** | `modules/interfaces/memory.py` | `sqlite` | `postgres`（future）|
| **模型路由** | `modules/interfaces/model_router.py` | `direct` | `litellm`、`openrouter`（future）|
| **认证** | `modules/interfaces/auth.py` | `whitelist` | `oauth2`、`ldap`（future）|
| **审计日志** | `modules/interfaces/audit.py` | `sqlite` | `elk`、`loki`（future）|
| **执行沙箱** | `modules/interfaces/sandbox.py` | `noop` | `docker`（Phase 1b）|
| **注入防护** | `modules/interfaces/prompt_guard.py` | `regex` | `llama-guard`、`lakera`（future）|
| **调度器** | `modules/interfaces/scheduler.py` | `apscheduler` | `celery`、`rq`（future）|

### 替换步骤（以把短期记忆换成 Redis 为例）

1. **实现接口**

```python
# modules/memory/redis_store.py
from modules.interfaces.memory import ShortTermMemoryInterface

class RedisStore(ShortTermMemoryInterface):
    async def get_context(self, user_id, conv_id): ...
    async def save_context(self, user_id, conv_id, messages): ...
    # ... 其余方法
```

2. **注册到 registry**

```python
# modules/registry.py  DRIVERS["short_term_memory"]
"redis": "modules.memory.redis_store:RedisStore",
```

3. **改配置，完成**

```json
// stone.config.json
"memory": {
  "short_term": { "driver": "redis" }
}
```

启动时 `ModuleLoader` 自动加载 `RedisStore`，其他代码零修改。

---

## 核心层：不可替换组件

以下组件是系统特有逻辑，没有通用三方组件可以平替，**不做乐高化，只保证解耦便于测试**。

### Agent（`core/agent.py`）

主处理循环，接收 `UserMessage`，驱动状态机执行，返回 `BotResponse`。

```
UserMessage → Agent.process()
  → StateMachine.run(ctx)
      → THINKING → TOOL_SELECTING → EXECUTING → RESPONDING
  → BotResponse
```

Agent 通过依赖注入接收所有可替换组件，本身不持有具体实现：

```python
Agent(
    model_router=...,     # ModelRouterInterface
    skill_registry=...,   # SkillRegistry
    context_manager=...,  # ContextManager
    dry_run_manager=...,  # DryRunManager
    audit_logger=...,     # AuditInterface
)
```

### StateMachine（`core/state_machine.py`）

7 状态机，转换表严格校验，防止非法跳转：

```
IDLE → THINKING → TOOL_SELECTING → EXECUTING
                ↘                ↗
              RESPONDING → IDLE
              ERROR_HANDLING → IDLE
              DRY_RUN_PENDING → THINKING (confirm) / IDLE (cancel)
```

### ContextManager（`core/context_manager.py`）

滑动窗口上下文管理 + 超限自动 Compact（摘要压缩）。依赖 `ShortTermMemoryInterface` 和 `LongTermMemoryInterface`，可通过换 driver 间接替换存储后端。

### DryRunManager（`core/dry_run.py`）

高风险操作的二次确认机制。生成执行计划 → 等待用户确认 → 执行或取消。

### SkillRegistry（`registry/skill_registry.py`）

工具注册中心，管理所有 `Tool` 的元数据和 JSON Schema，供 Agent 构建 LLM function-calling 参数。

---

## 目录结构

```
stone/
├── main.py                    # FastAPI 入口，lifespan 管理
├── config.py                  # 环境变量 (pydantic-settings)
├── stone.config.json          # 模块 driver 配置
│
├── core/                      # 核心层（不可替换）
│   ├── agent.py               # Agent 主循环
│   ├── state_machine.py       # 7状态机
│   ├── context_manager.py     # 上下文滑动窗口
│   ├── dry_run.py             # 干跑确认机制
│   ├── model_router.py        # LLM 路由（实现 ModelRouterInterface）
│   ├── scheduler.py           # 定时任务（实现 SchedulerInterface）
│   └── persona.md             # 默行者人格 system prompt
│
├── modules/                   # 可替换层
│   ├── interfaces/            # 9 个 ABC 接口定义
│   ├── registry.py            # DRIVERS 字典 + load_driver()
│   ├── loader.py              # 14步启动，读 driver 配置动态加载
│   ├── gateway/feishu.py      # 飞书 WebSocket 网关
│   ├── memory/
│   │   ├── inmemory_store.py  # 短期记忆（内存）
│   │   └── sqlite_store.py    # 长期记忆（SQLite）
│   └── sandbox/
│       ├── noop.py            # Phase 1 沙箱（无隔离）
│       └── docker.py          # Phase 1b 沙箱（Docker）
│
├── security/                  # 安全模块（实现对应接口）
│   ├── auth.py                # 白名单 + bcrypt PIN + TOTP
│   ├── audit.py               # 审计日志
│   └── prompt_guard.py        # 10种注入模式检测
│
├── tools/                     # 工具实现
│   ├── base.py                # ToolInterface ABC
│   ├── file_tool.py           # 文件读写（白名单目录）
│   ├── bash_tool.py           # Shell 命令（白名单，Phase 1a 无沙箱）
│   └── search_tool.py         # Tavily 搜索
│
├── models/                    # Pydantic 数据模型
├── api/                       # FastAPI 路由
│   ├── chat.py                # POST /api/chat
│   ├── health.py              # GET /health
│   └── admin.py               # GET/POST /api/admin/*
├── registry/skill_registry.py # 工具注册中心
└── tests/                     # 318 个测试（全部通过）
```

---

## 快速开始

### 1. 配置环境

```bash
cp .env.example .env
# 填写以下字段：
# ZHIPUAI_API_KEY        智谱 GLM API Key
# DASHSCOPE_API_KEY      阿里云通义 API Key
# FEISHU_APP_ID          飞书自建应用 ID
# FEISHU_APP_SECRET      飞书自建应用 Secret
# ADMIN_WHITELIST        你的飞书 open_id（逗号分隔）
# ADMIN_PIN              管理员 PIN（bcrypt hash）
# WORKSPACE_DIR          Agent 工作目录（需提前创建）
# TAVILY_API_KEY         Tavily 搜索 API Key
```

### 2. 启动本地模型

```bash
ollama run qwen2.5:14b
```

### 3. 安装依赖并运行

```bash
pip install -r requirements.txt
python main.py
# 访问 http://localhost:8000/health 验证启动状态
```

### 4. 运行测试

```bash
pytest tests/ -v
# 预期：318 passed
```

---

## 开发路线

| 阶段 | 目标 | 状态 |
|------|------|------|
| Phase 1a | 最小可对话链路（飞书 + 3工具 + SQLite）| ✅ 完成 |
| Phase 1b | Docker 沙箱 + PIN/TOTP + 更多工具 | 🔄 进行中 |
| Phase 2  | MCP、Redis、Telegram/WeChat 网关 | 📋 计划中 |
| Phase 3  | RAG（ChromaDB + LlamaIndex）| 📋 计划中 |
| Phase 4  | 微调 + Web UI | 📋 计划中 |

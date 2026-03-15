# 默行者 STONE v0.1.0

> **S**elf-hosted Personal AI **T**ask Agent with **O**llama-first privacy routing and **N**ative **E**xecution — **默行者**，沉默而高效地执行你的指令。

一个运行在你自己服务器上的私人 AI 助手，通过**飞书（Lark）消息**与你对话，具备真实的文件操作、代码执行、网络搜索、笔记管理等能力。核心设计目标：**隐私优先、可审计、不过度依赖云端**。

---

## 亮点

| 特性 | 说明 |
|------|------|
| 🔒 **隐私感知路由** | 敏感内容 → 本地 Ollama；代码任务 → DashScope qwen-coder-plus；通用对话 → ZhipuAI GLM-4-plus |
| 🛡️ **危险操作二次确认** | 删除文件/目录、执行 Shell 命令等操作生成 dry-run 预览计划，用户回复「确认」才执行 |
| 🔗 **飞书原生接入** | WebSocket 长连接，消息实时到达，支持私聊和群聊 |
| 🧠 **7 状态机驱动** | IDLE → THINKING → TOOL_SELECTING → DRY_RUN_PENDING → EXECUTING → RESPONDING → ERROR_HANDLING |
| 📋 **上下文持久化** | 滑动窗口 + LLM 摘要压缩，SQLite 持久化，重启不丢失对话历史 |
| 🕒 **定时任务** | APScheduler 驱动，支持 cron 表达式，可通过 API 管理计划任务 |
| 🔌 **模块化架构** | Gateway / Memory / Sandbox / Auth 均可通过 `stone.config.json` 替换实现 |

---

## 能力一览

### 工具集

| 工具 | 能做什么 |
|------|---------|
| `file_tool` | 读写文件、创建/删除目录、列目录（沙盒限制在 WORKSPACE_DIR 内） |
| `bash_tool` | 在受控环境执行 Shell 命令（危险命令需确认） |
| `code_tool` | 在 Docker 容器或 Noop 沙盒中安全运行 Python 代码片段 |
| `search_tool` | Tavily API 驱动的网络搜索，返回摘要结果 |
| `note_tool` | 在 NOTES_DIR 下创建/读取/列出 Markdown 笔记 |
| `http_tool` | 发起 HTTP 请求，抓取网页内容（BeautifulSoup 解析） |
| `git_tool` | git status / diff / commit / log（限制在指定仓库） |

### 多意图顺序执行

用户说「先删除旧目录，再写入新文件，然后搜索最新资讯」，STONE 会**严格按顺序**逐步执行，每步等待工具返回结果后再决定下一步，不会跳过需要确认的步骤。

### 对话记忆

- 短期：每个 `conv_id`（飞书 `chat_id`）独立的消息窗口（默认 20 轮）
- 长期：超出窗口时 LLM 自动生成摘要，存入 SQLite，下次对话恢复
- 重启后从 SQLite 恢复上下文，无需重新建立背景

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                     可替换层（乐高化）                         │
│                                                              │
│  Gateway       Memory        Auth         Sandbox           │
│  Feishu WS  │  SQLite /   │  白名单 /   │  Noop /          │
│  (Telegram) │  InMemory   │  TOTP+PIN   │  Docker          │
│                                                              │
│  ModelRouter         Audit          PromptGuard             │
│  Ollama/ZhipuAI/  │  SQLite /    │  关键词 /              │
│  DashScope        │  文件日志     │  正则扫描               │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│                       核心层（不乐高化）                       │
│                                                              │
│   Agent (state machine)  ←→  ContextManager                 │
│         ↕                         ↕                         │
│   ToolRegistry / DryRunManager   SQLite (aiosqlite)         │
└──────────────────────────────────────────────────────────────┘
```

### 模型路由逻辑

```
请求 → privacy_sensitive?
  ├─ 是 → Ollama (qwen2.5:14b，本地，不出网)
  └─ 否 → task_type?
          ├─ code → DashScope qwen-coder-plus
          └─ 其他 → ZhipuAI GLM-4-plus
                   (token 超限时降级到 Ollama)
```

### 安全机制

- **白名单认证**：只有 `ADMIN_WHITELIST` 中的飞书 open_id 可以发消息
- **滑动窗口限流**：每用户 20 条/60 秒
- **Prompt Injection 扫描**：检测并拦截提示词注入攻击
- **危险操作 dry-run**：`delete_file`、`delete_dir`、`bash_tool` 等需用户二次确认
- **TOTP + bcrypt PIN 双因子**：Admin API 需要 TOTP 验证码 + bcrypt PIN
- **安全审计日志**：白名单拦截、限流、注入攻击均写入审计表

---

## 快速开始

### 前提条件

- Python 3.11+
- [Ollama](https://ollama.ai) 已运行，已拉取 `qwen2.5:14b`（或其他模型）
- 飞书自建应用，开通「接收消息」权限，启用 WebSocket 长连接
- ZhipuAI 和/或 DashScope API Key（可只用 Ollama 本地模式）

### 安装

```bash
git clone git@github.com:Tao-AIcoder/stone.git
cd stone
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的密钥和配置
```

关键配置项：

```env
# 飞书应用凭证
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx

# 允许使用的飞书用户 open_id（逗号分隔）
ADMIN_WHITELIST=ou_xxxxxxxx,ou_yyyyyyyy

# 模型 API Key
ZHIPUAI_API_KEY=xxx
DASHSCOPE_API_KEY=sk-xxx

# 本地 Ollama 地址
OLLAMA_BASE_URL=http://localhost:11434

# 工作目录（file_tool 沙盒根目录）
WORKSPACE_DIR=/home/you/stone-workspace
NOTES_DIR=/home/you/notes

# 网络搜索（可选）
TAVILY_API_KEY=tvly-xxx

# Admin 认证
ADMIN_PIN=<bcrypt hash>
TOTP_SECRET=<BASE32>
```

模块驱动配置（`stone.config.json`）：

```json
{
  "gateway": "feishu",
  "memory_backend": "sqlite",
  "sandbox": "noop",
  "auth_backend": "whitelist"
}
```

### 启动

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0"}
```

---

## API

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `GET /api/admin/tasks` | 查看定时任务（需 TOTP） |
| `POST /api/admin/tasks` | 创建定时任务 |
| `DELETE /api/admin/tasks/{id}` | 删除定时任务 |
| `GET /api/admin/skills` | 查看已注册技能 |
| `GET /api/admin/audit` | 审计日志 |

---

## 飞书交互示例

```
你：帮我创建目录 projects/stone，然后写一个 hello.py
STONE：收到，处理中，请稍候...
STONE：已创建目录 projects/stone，已写入 hello.py

你：删除 projects/old_backup 目录
STONE：以下操作需要确认：
       • delete_dir: projects/old_backup
       回复「确认」执行 / 回复「取消」放弃

你：确认
STONE：已删除目录 projects/old_backup

你：搜索 Claude 4 最新发布信息
STONE：[搜索结果摘要...]
```

---

## 测试

```bash
pytest tests/ -v
```

关键测试覆盖：
- `test_bug_tool_dispatch.py` — 工具分发链路、正则解析、参数清洗
- `test_state_machine.py` — 状态机合法/非法转换
- `test_dry_run.py` — 危险操作确认流程
- `test_context_manager.py` — 上下文压缩与恢复

---

## 项目结构

```
stone/
├── main.py                 # FastAPI 入口
├── config.py               # Pydantic Settings 配置
├── stone.config.json       # 模块驱动配置
├── core/
│   ├── agent.py            # 核心状态机 + 工具分发
│   ├── model_router.py     # 多模型路由
│   ├── context_manager.py  # 对话上下文管理
│   ├── dry_run.py          # 危险操作 dry-run 管理
│   ├── scheduler.py        # APScheduler 定时任务
│   └── state_machine.py    # 状态转换验证
├── tools/                  # 工具实现
│   ├── file_tool.py
│   ├── bash_tool.py
│   ├── code_tool.py
│   ├── search_tool.py
│   ├── note_tool.py
│   ├── http_tool.py
│   └── git_tool.py
├── modules/
│   ├── gateway/feishu.py   # 飞书 WebSocket 网关
│   ├── memory/             # 短期+长期记忆
│   └── sandbox/            # 代码执行沙盒
├── security/               # Auth / AuditLogger / PromptGuard
├── models/                 # Pydantic 数据模型
├── api/                    # FastAPI 路由
├── registry/               # 工具/技能注册表
└── tests/                  # 单元测试
```

---

## 路线图

- [ ] Telegram Bot 网关（gateway 接口已预留）
- [ ] Redis 短期记忆后端（替换 InMemory）
- [ ] 向量记忆（modules/vector 已预留接口）
- [ ] 更多内置工具（calendar_tool、email_tool）
- [ ] Web UI 管理面板
- [ ] 多用户隔离沙盒

---

## License

MIT License. See [LICENSE](LICENSE).

---

*默行者 — 沉默而高效。*

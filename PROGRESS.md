# 默行者 (STONE) 开发进度

> 本文件供 Claude Code 追踪项目进度，每次会话开始前应先读取此文件。
> 最后更新：2026-03-13

---

## 当前阶段：Phase 1a —— 最小可对话链路（乐高架构已完成）

### 验收标准
- [ ] 在飞书上能对话
- [ ] 能搜索（Tavily API）
- [ ] 能读写文件（白名单目录内）

---

## Phase 1a 任务清单（第1周）

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 1 | 项目骨架 + 配置文件 | `stone.config.json`, `config.py`, `.env.example` | ✅ 已生成 | 需填写真实 API Key |
| 2 | 数据模型层 | `models/` 全部 7 个文件 | ✅ 已生成 | Pydantic v2 |
| 3 | 异常体系 | `models/errors.py` | ✅ 已生成 | 14个异常类 |
| 4 | Agent 状态机 | `core/state_machine.py` | ✅ 已生成 | 7状态，转换表强制校验 |
| 5 | 模型路由器 | `core/model_router.py` | ✅ 已生成 | Ollama + 智谱 + 阿里云 |
| 6 | Agent 主循环 | `core/agent.py` | ✅ 已生成 | 状态机驱动 |
| 7 | 上下文管理 | `core/context_manager.py` | ✅ 已生成 | 滑动窗口 + Compact |
| 8 | 默行者人格 | `core/persona.md` | ✅ 已生成 | 中文 system prompt |
| 9 | 工具基类 | `tools/base.py` | ✅ 已生成 | ToolInterface ABC |
| 10 | file_tool | `tools/file_tool.py` | ✅ 已生成 | 白名单目录，防路径穿越 |
| 11 | bash_tool | `tools/bash_tool.py` | ✅ 已生成 | 白名单命令，无沙箱(1a) |
| 12 | search_tool | `tools/search_tool.py` | ✅ 已生成 | Tavily API |
| 13 | 短期记忆 | `modules/memory/inmemory_store.py` | ✅ 已生成 | asyncio.Lock 线程安全 |
| 14 | 长期存储 | `modules/memory/sqlite_store.py` | ✅ 已生成 | 6张表 + CRUD |
| 15 | 白名单认证 | `security/auth.py` | ✅ 已生成 | bcrypt PIN + TOTP |
| 16 | 审计日志 | `security/audit.py` | ✅ 已生成 | 写 SQLite，敏感字段脱敏 |
| 17 | Prompt 防护 | `security/prompt_guard.py` | ✅ 已生成 | 10种注入模式检测 |
| 18 | 能力注册中心 | `registry/skill_registry.py` | ✅ 已生成 | Phase 1a 3工具注册 |
| 19 | 飞书网关 | `modules/gateway/feishu.py` | ✅ 已生成 | WebSocket，断线重连 |
| 20 | 模块加载器 | `modules/loader.py` | ✅ 重构完成 | 读 stone.config.json driver 字段动态加载 |
| 21 | 健康检查 API | `api/health.py` | ✅ 已生成 | GET /health |
| 22 | 对话 API | `api/chat.py` | ✅ 已生成 | POST /api/chat |
| 23 | FastAPI 入口 | `main.py` | ✅ 已生成 | lifespan + 路由挂载 |
| 24 | **环境配置** | `.env` (本地，gitignore) | ⚠️ 待填写 | 复制 .env.example 填写真实 Key |
| 25 | **单元/接口测试** | `tests/` 全部测试 | ✅ 318个测试，全部通过 | 2026-03-13 |
| 26 | **端对端测试** | 飞书发消息 → 收到回复 | ⏳ 待执行 | 需要真实环境 |

---

## 乐高化架构（已完成）

### 核心文件
| 文件 | 作用 |
|------|------|
| `modules/interfaces/` | 8个 ABC 接口定义，覆盖所有可替换模块 |
| `modules/registry.py` | `DRIVERS` 字典 + `load_driver(component, driver)` 动态加载 |
| `modules/loader.py` | 读取 `stone.config.json` driver 字段，通过 registry 加载模块 |
| `modules/sandbox/noop.py` | Phase 1 无 Docker 沙箱（subprocess，非隔离） |

### 接口列表
| 接口 | 文件 | 当前实现 | 替换方式 |
|------|------|----------|----------|
| `GatewayInterface` | `modules/interfaces/gateway.py` | `FeishuGateway` | 修改 `modules.gateway.driver` |
| `ShortTermMemoryInterface` | `modules/interfaces/memory.py` | `InMemoryStore` | 修改 `modules.memory.short_term.driver` |
| `LongTermMemoryInterface` | `modules/interfaces/memory.py` | `SQLiteStore` | 修改 `modules.memory.long_term.driver` |
| `ModelRouterInterface` | `modules/interfaces/model_router.py` | `ModelRouter` | 修改 `modules.model_router.driver` |
| `AuthInterface` | `modules/interfaces/auth.py` | `AuthManager` | 修改 `modules.auth.driver` |
| `AuditInterface` | `modules/interfaces/audit.py` | `AuditLogger` | 修改 `modules.audit.driver` |
| `SandboxInterface` | `modules/interfaces/sandbox.py` | `NoopSandbox`/`DockerSandbox` | 修改 `modules.sandbox.driver` |
| `PromptGuardInterface` | `modules/interfaces/prompt_guard.py` | `PromptGuard` | 修改 `modules.prompt_guard.driver` |

### 独立模块测试
| 测试文件 | 覆盖范围 |
|----------|----------|
| `tests/test_module_registry.py` | DRIVERS 完整性、load_driver、接口合规性 |
| `tests/test_module_memory_inmemory.py` | InMemoryStore CRUD、LRU、并发安全 |
| `tests/test_module_auth.py` | AuthManager 白名单、PIN、TOTP、限流 |
| `tests/test_module_sandbox_noop.py` | NoopSandbox execute/run_bash/timeout |
| `tests/test_module_prompt_guard.py` | PromptGuard scan/scan_safe/wrap_untrusted |

---

## Phase 1b 任务清单（第2周）

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 1 | Docker 沙箱 | `modules/sandbox/docker.py` | 📋 骨架已生成 | 实现容器执行、资源限制 |
| 2 | bash_tool 接入沙箱 | `tools/bash_tool.py` | 📋 待升级 | 危险命令走Docker |
| 3 | code_tool | `tools/code_tool.py` | 📋 骨架已生成 | 沙箱执行 Python/JS |
| 4 | git_tool | `tools/git_tool.py` | 📋 骨架已生成 | commit/push 需确认 |
| 5 | note_tool | `tools/note_tool.py` | 📋 骨架已生成 | Obsidian REST API |
| 6 | http_tool | `tools/http_tool.py` | 📋 骨架已生成 | 外部 HTTP 调用 |
| 7 | 干跑模式 | `core/dry_run.py` | ✅ 已生成 | 待集成测试 |
| 8 | PIN + TOTP 认证 | `security/auth.py` | ✅ 已完成 | bcrypt + pyotp（1a已含） |
| 9 | 管理员 API | `api/admin.py` | ✅ 已生成 | 待认证集成 |
| 10 | 定时任务引擎 | `core/scheduler.py` | ✅ 已生成 | 待集成测试 |
| 11 | 安全测试覆盖 | `tests/` | 📋 继续扩展 | 当前 318 测试 |

---

## Phase 2（第3-4周，未开始）

- [ ] MCP Server 接入（`registry/mcp_manager.py`）
- [ ] 奇门遁甲工具（`tools/qimen_tool.py`）
- [ ] 浏览器工具（`tools/browser_tool.py`，Playwright）
- [ ] Redis 切换短期记忆（`modules/memory/redis_store.py`）
- [ ] Cloudflare Tunnel 公网接入

---

## Phase 3（第5-7周，未开始）

- [ ] RAG 管道（ChromaDB + LlamaIndex）
- [ ] 向量存储（`modules/vector/`）
- [ ] 文档嵌入（PDF/Markdown/Word）

---

## Phase 4（第8-10周，未开始）

- [ ] LLaMA-Factory 微调
- [ ] Web UI

---

## 立即要做的事（下次会话必看）

### 🔴 优先级1：配置环境（能跑起来的前提）
1. 复制 `.env.example` → `.env`，填写：
   - `ZHIPUAI_API_KEY`（智谱 GLM）
   - `DASHSCOPE_API_KEY`（阿里云通义）
   - `FEISHU_APP_ID` + `FEISHU_APP_SECRET`（飞书自建应用）
   - `ADMIN_WHITELIST`（你的飞书 open_id）
   - `WORKSPACE_DIR`（Agent 工作目录，需提前创建）
   - `TAVILY_API_KEY`（搜索功能）
2. 确认 Ollama 已运行：`ollama run qwen2.5:14b`
3. 安装依赖：`pip install -r requirements.txt`
4. 首次运行：`python main.py`

### 🟡 优先级2：排查启动问题
- 运行后检查 `/health` 端点各模块状态
- 重点检查：model_router 能否连通 Ollama / 智谱 / 阿里云
- 飞书 WebSocket 是否成功连接

### 🟢 优先级3：Phase 1b 实现
- Docker 沙箱是最关键的安全组件
- 完成后运行 tests/ 下的安全测试

---

## 已归档 Bug（已修复）

| Bug | 位置 | 修复方式 |
|-----|------|---------|
| `conv_id=body.conv_id or None` 导致 ValidationError | `api/chat.py:52` | 改为条件展开 dict |
| `TOOL_SELECTING→THINKING` 非法转换 | `tests/test_state_machine.py` | 改为 3 状态合法循环 |
| 正则不匹配 "disable your content guardrails" | `security/prompt_guard.py` | 加 `(\w+\s+)?` 允许中间词 |
| 中文正则不匹配 "忽略之前的所有指令" | `security/prompt_guard.py` | 改为 `.{0,15}` 模糊匹配 |
| "ignore all previous instructions" 匹配缺失 | `security/prompt_guard.py` | 允许中间额外词 |

## 技术债 / 已知问题

| 问题 | 位置 | 影响 |
|------|------|------|
| bash_tool Phase 1a 无沙箱 | `tools/bash_tool.py` | 中风险，Phase 1b 升级 |
| health.py 用全局 _loader 而非 request.app.state.loader | `api/health.py` | 测试需 patch，Phase 1b 重构 |
| 模型路由任务类型判断较简单 | `core/model_router.py` | 低风险，后续优化 |
| 飞书重连测试未完成 | `modules/gateway/feishu.py` | 需真实环境测试 |

---

## 项目信息

- **GitHub**：https://github.com/Tao-AIcoder/stone（私有）
- **本地路径**：`~/stone/`
- **Python 版本**：3.11+
- **主入口**：`python main.py`（uvicorn 默认 8000 端口）

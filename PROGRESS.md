# 默行者 (STONE) 开发进度

> 本文件供 Claude Code 追踪项目进度，每次会话开始前应先读取此文件。
> 最后更新：2026-03-16（第六次会话）

---

## 当前阶段：Phase 1b 调测完成 ✅ 663 tests passing

### 验收标准
- [x] 在飞书上能对话 ✅（2026-03-14 验证，GLM-4-plus + Ollama fallback）
- [x] 能搜索（Tavily API）✅（2026-03-14 验证，20个集成测试全通过）
- [x] 能读写文件（白名单目录内）✅（2026-03-14 验证，13个集成测试全通过）

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
| 25 | **单元/接口测试** | `tests/` 全部测试 | ✅ 501个测试，全部通过 | 2026-03-14（第四次会话新增48个测试，含工具集成+降级+安全修复） |
| 26 | **端对端测试** | 飞书发消息 → 收到回复 | ⏳ 待执行 | 需要真实环境 |

---

## 乐高化架构（已完成）

### 核心文件
| 文件 | 作用 |
|------|------|
| `modules/interfaces/` | 9个 ABC 接口定义，覆盖所有可替换模块 |
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
| `SchedulerInterface` | `modules/interfaces/scheduler.py` | `Scheduler` | 修改 `modules.scheduler.driver` |

### 独立模块测试
| 测试文件 | 覆盖范围 |
|----------|----------|
| `tests/test_module_registry.py` | DRIVERS 完整性、load_driver、接口合规性 |
| `tests/test_module_memory_inmemory.py` | InMemoryStore CRUD、LRU、并发安全 |
| `tests/test_module_auth.py` | AuthManager 白名单、PIN、TOTP、限流 |
| `tests/test_module_sandbox_noop.py` | NoopSandbox execute/run_bash/timeout |
| `tests/test_module_prompt_guard.py` | PromptGuard scan/scan_safe/wrap_untrusted |

### 黑盒 API 测试（第二次会话新增，135个）
| 测试文件 | 覆盖范围 |
|----------|----------|
| `tests/test_blackbox_health.py` | /health schema 稳定性 |
| `tests/test_blackbox_chat.py` | /api/chat 全路径（happy path/validation/auth/dry-run） |
| `tests/test_blackbox_admin.py` | 所有 admin 端点、认证强制执行、CRUD 合约 |
| `tests/test_blackbox_error_handling.py` | 错误格式、404、方法错误、幂等性 |
| `tests/test_blackbox_contracts.py` | 字段必须存在、类型稳定、JSON 合法 |

---

## Phase 1b 任务清单（调整版，2026-03-15）

### 需求1：长期记忆 + 遗忘曲线

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 1 | 本地模型管理器 | `modules/memory/local_model_manager.py` | ✅ 已生成 |
| 2 | Embedding 接口 | `modules/interfaces/embedding.py` | ✅ 已生成 |
| 3 | sentence-transformers 后端 | `modules/memory/embedding_backends/sentence_transformers_backend.py` | ✅ 已生成 |
| 4 | Ollama embedding 后端 | `modules/memory/embedding_backends/ollama_backend.py` | ✅ 已生成 |
| 5 | 记忆存储（遗忘曲线）| `modules/memory/memory_store.py` | ✅ 已生成 |
| 6 | 记忆提取器 | `modules/memory/memory_extractor.py` | ✅ 已生成 |
| 7 | memory_tool | `tools/memory_tool.py` | ✅ 已生成 |
| 8 | Agent 对话后提取钩子 | `core/agent.py`（修改）| ✅ 已生成 |
| 9 | 每周用户画像定时任务 | `core/scheduler.py`（修改）| ✅ 已生成 |

**遗忘曲线参数（可配置）：**
- `decay_rate`: 衰减速率 λ（默认 0.05/天）
- `compress_threshold`: 强度 < 0.5 → 压缩内容
- `forget_threshold`: 强度 < 0.1 → 删除
- `max_size_kb`: 记忆总大小上限（默认 512KB）
- 被访问/强化时强度重置；用户夸奖强化上一条 AI 回复行为 +0.2

### 需求2：MCP Server 接入（乐高化）

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 10 | MCP Server 接口 | `modules/interfaces/mcp_server.py` | ✅ 已生成 |
| 11 | MCP Client | `modules/mcp/client.py` | ✅ 已生成 |
| 12 | MCP 进程管理器 | `modules/mcp/process_manager.py` | ✅ 已生成 |

**设计要点：** 标准 MCP Client，stdio/SSE 双传输；印象笔记国内版 + 百度网盘均用官方 MCP Server；新增 Server 只改配置，STONE 零改动。

### 需求3：HTTP Tool

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 13 | HTTP Client 接口 | `modules/interfaces/http_client.py` | ✅ 已生成 |
| 14 | HTTP Tool 完整实现 | `tools/http_tool.py`（重写）| ✅ 已生成 |

### 需求4：Note Tool（本地 + 云端）

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 15 | Note Backend 接口 | `modules/interfaces/note_backend.py` | ✅ 已生成 |
| 16 | 本地 Note 后端 | `modules/note_backends/local_backend.py` | ✅ 已生成 |
| 17 | MCP 云端 Note 后端 | `modules/note_backends/mcp_backend.py` | ✅ 已生成 |
| 18 | Note Tool 重构 | `tools/note_tool.py`（重写）| ✅ 已生成 |

**路由逻辑：** 显式关键词（存到印象笔记/百度网盘）→ MCP 后端；其余 → 本地默认。

### 需求5：Office Tool

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 19 | Office Tool 接口 | `modules/interfaces/office_tool_interface.py` | ✅ 已生成 |
| 20 | Office Tool 实现 | `tools/office_tool.py` | ✅ 已生成 |

**支持格式：** .docx / .xlsx / .pptx；Phase 1b 做内容 + 基础样式（标题/粗斜体/列表/表格/单元格格式）；图片/公式/动画留后。

### 配置 & 注册

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 21 | 配置扩展 | `stone.config.json`（修改）| ✅ 已生成 |
| 22 | 依赖更新 | `requirements.txt`（修改）| ✅ 已生成 |
| 23 | 驱动注册 | `modules/registry.py`（修改）| ✅ 已生成 |
| 24 | 人格更新 | `core/persona.md`（修改）| ✅ 已生成 |

### 测试

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 25 | 记忆遗忘曲线测试 | `tests/test_memory_forgetting.py` | ✅ 调测通过 |
| 26 | 记忆提取测试 | `tests/test_memory_extractor.py` | ✅ 调测通过 |
| 27 | MCP Client 测试 | `tests/test_mcp_client.py` | ✅ 调测通过 |
| 28 | HTTP Tool 测试 | `tests/test_http_tool.py` | ✅ 调测通过 |
| 29 | Note Tool 测试 | `tests/test_note_tool.py` | ✅ 调测通过 |
| 30 | Office Tool 测试 | `tests/test_office_tool.py` | ✅ 调测通过 |
| 31 | LocalModelManager 测试 | `tests/test_local_model_manager.py` | ✅ 调测通过 |

---

### Phase 1b 调测结果（2026-03-16）

**总计：663 tests，0 failures**

修复的 Bug：
1. `skill_registry.py`：`NoteTool()` → `NoteTool(local_backend=LocalNoteBackend())`，新增 OfficeTool 注册
2. `test_memory_forgetting.py`：async fixture 改为 sync + `run_until_complete()`（pytest-asyncio 1.x 兼容）
3. `memory_extractor.py`：`is_praise()` 单字仅精确匹配，防止 `'不对'` 误判为表扬
4. `http_tool.py`：`_is_private_ip()` DNS 失败时 fail-safe 返回 True（SSRF 防护）
5. `test_tool_search.py`：Tavily API 网络不稳定时自动 skip，不阻断 CI

**待办（Phase 2 优先）：**
- 飞书端到端集成测试（需真实环境）
- MCP Server 真实连接测试（需 evernote/baidu_netdisk MCP 服务启动）

---

## Phase 2（调整后）

- [ ] 浏览器工具（`tools/browser_tool.py`，Playwright）
- [ ] Redis 切换短期记忆（`modules/memory/redis_store.py`）
- [ ] Cloudflare Tunnel 公网接入
- [ ] 奇门遁甲工具（`tools/qimen_tool.py`）

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

## 下次会话必看

### Phase 1b 调测顺序
1. 安装新依赖：`pip install -r requirements.txt`
2. 第一轮：`pytest tests/test_mcp_client.py tests/test_http_tool.py -v`
3. 第二轮：`pytest tests/test_memory_forgetting.py tests/test_memory_extractor.py tests/test_local_model_manager.py -v`
4. 第三轮：MCP 真实连接测试（需印象笔记/百度网盘 token）
5. 第四轮：`pytest tests/test_note_tool.py tests/test_office_tool.py -v`
6. 第五轮：飞书端到端黑盒测试

---

## 已归档 Bug（已修复）

| Bug | 位置 | 修复方式 | 发现时机 |
|-----|------|---------|---------|
| `conv_id=body.conv_id or None` 导致 ValidationError | `api/chat.py:52` | 改为条件展开 dict | 第一次会话 |
| `TOOL_SELECTING→THINKING` 非法转换 | `tests/test_state_machine.py` | 改为 3 状态合法循环 | 第一次会话 |
| 正则不匹配 "disable your content guardrails" | `security/prompt_guard.py` | 加 `(\w+\s+)?` 允许中间词 | 第一次会话 |
| 中文正则不匹配 "忽略之前的所有指令" | `security/prompt_guard.py` | 改为 `.{0,15}` 模糊匹配 | 第一次会话 |
| "ignore all previous instructions" 匹配缺失 | `security/prompt_guard.py` | 允许中间额外词 | 第一次会话 |
| `/api/chat` 无白名单检查 | `api/chat.py` | 加 `verify_user()` → 403 | 黑盒测试发现 |
| `/api/chat` 无 Prompt 防护 | `api/chat.py` | 加 `prompt_guard.scan()` → 400 | 黑盒测试发现 |
| `content=""` 空字符串被接受 | `api/chat.py` | 加 `field_validator` → 422 | 黑盒测试发现 |
| `DockerSandbox` 继承了错误父类 | `modules/sandbox/docker.py` | 改为继承 `SandboxInterface` | 第二次会话架构审视 |
| `stone.config.json` 缺少 3 个 driver 字段 | `stone.config.json` | 补全 auth/audit/prompt_guard driver | 第二次会话 |
| `sandbox.driver="docker"` 指向未实现存根 | `stone.config.json` | 改为 `"noop"` | 第二次会话 |
| `ADMIN_WHITELIST` pydantic-settings 格式错误 | `.env` | 改为 JSON 数组 `["id"]` | 第三次会话 |
| `asyncio.get_event_loop()` 在 pytest-asyncio strict 模式下拿到错误 loop | `tools/search_tool.py`, `core/model_router.py`（zhipuai + dashscope） | 全部改为 `asyncio.get_running_loop()` | 第四次会话 |
| `/api/conversations/{conv_id}/history` 无白名单检查 | `api/chat.py` | 加 `verify_user()` → 403 | 第四次会话 |
| `health.py` 用全局 `get_loader()` 绕过 app.state.loader | `api/health.py` | 优先读 `request.app.state.loader`，降级回全局 | 第四次会话 |
| `lark_oapi.ws.client.loop` 捕获 uvloop 导致 already running | `modules/gateway/feishu.py` | 子线程创建新 loop + threading.Lock 串行 | 第三次会话 |
| `t.join()` 同步阻塞 uvicorn 事件循环 | `modules/gateway/feishu.py` | 改为 `await run_in_executor(None, t.join)` | 第三次会话 |
| `_on_message_receive` 是 async 但 SDK 同步调用，coroutine 从未 await | `modules/gateway/feishu.py` | `_sync_on_message` + `run_coroutine_threadsafe` fire-and-forget | 第三次会话 |
| `_sync_on_message` 等待 `future.result(60s)` 阻塞 WS 事件循环 | `modules/gateway/feishu.py` | 改为 fire-and-forget，不等结果 | 第三次会话 |

## 技术债 / 已知问题

| 问题 | 位置 | 影响 |
|------|------|------|
| bash_tool Phase 1a 无沙箱 | `tools/bash_tool.py` | 中风险，Phase 1b 升级 |
| ~~health.py 用全局 _loader 而非 request.app.state.loader~~ | ✅ 已修复 | — |
| 模型路由任务类型判断较简单 | `core/model_router.py` | 低风险，后续优化 |
| 飞书重连测试未完成 | `modules/gateway/feishu.py` | 需真实环境测试 |

---

## 项目信息

- **GitHub**：https://github.com/Tao-AIcoder/stone（公开，v0.1.0已发布）
- **本地路径**：`~/stone/`
- **Python 版本**：3.11+
- **主入口**：`python main.py`（uvicorn 默认 8000 端口）

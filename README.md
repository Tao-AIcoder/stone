# 默行者 STONE v0.2.0-dev

> **S**elf-hosted Personal AI **T**ask Agent with **O**llama-first privacy routing and **N**ative **E**xecution — **默行者**，沉默而高效地执行你的指令。

一个运行在你自己服务器上的私人 AI 助手，通过**飞书（Lark）消息**与你对话，具备真实的文件操作、代码执行、网络搜索、笔记管理、Office 文档处理、长期记忆等能力。核心设计目标：**隐私优先、可审计、不过度依赖云端**。

---

## 亮点

| 特性 | 说明 |
|------|------|
| 🔒 **隐私感知路由** | 敏感内容 → 本地 Ollama；代码任务 → DashScope qwen-coder-plus；通用对话 → ZhipuAI GLM-4-plus |
| 🧠 **长期记忆 + 遗忘曲线** | 指数衰减 `e^(-λt)`，压缩/遗忘阈值可配，用户夸奖强化 AI 行为记忆 |
| 🔌 **MCP Server 乐高接入** | 标准 MCP Client（stdio），印象笔记国内版 + 百度网盘官方 MCP Server，新增 Server 零改代码 |
| 🛡️ **危险操作二次确认** | 删除/写入等操作生成 dry-run 预览，用户回复「确认」才执行 |
| 🔗 **飞书原生接入** | WebSocket 长连接，消息实时到达，支持私聊和群聊 |
| 📋 **7 状态机驱动** | IDLE → THINKING → TOOL_SELECTING → DRY_RUN_PENDING → EXECUTING → RESPONDING → ERROR_HANDLING |
| 📦 **上下文持久化** | 滑动窗口 + LLM 摘要压缩，SQLite 持久化，重启不丢失对话历史 |
| 🕒 **定时任务** | APScheduler 驱动，支持 cron 表达式，可通过 API 管理计划任务 |
| 🔑 **模块化架构** | Gateway / Memory / Sandbox / Auth 均可通过 `stone.config.json` 替换实现 |

---

## 能力一览

### 工具集

| 工具 | 能做什么 | 阶段 |
|------|---------|------|
| `file_tool` | 读写文件、创建/删除目录、列目录（沙盒限制在 WORKSPACE_DIR 内） | 1a |
| `bash_tool` | 在受控环境执行 Shell 命令（危险命令需确认） | 1a |
| `code_tool` | 在 Docker 容器或 Noop 沙盒中安全运行 Python 代码片段 | 1a |
| `search_tool` | Tavily API 驱动的网络搜索，返回摘要结果 | 1a |
| `git_tool` | git status / diff / commit / log（限制在指定仓库） | 1a |
| `http_tool` | 向任意 URL 发 HTTP 请求，SSRF 防护，HTML 解析，1MB 截断 | 1b |
| `note_tool` | 本地 Markdown 笔记 CRUD + 关键词搜索；可路由到印象笔记/百度网盘（MCP） | 1b |
| `office_tool` | 创建/读取/追加 Word (.docx) / Excel (.xlsx) / PPT (.pptx)，支持 Markdown 转文档 | 1b |
| `memory_tool` | 长期记忆的显式增删查；用户主动「请记住」直接触发 | 1b |

### 长期记忆系统

```
每轮对话结束后：
  用户消息含"请记住" → 显式记忆（低衰减率 0.5×）
  否则 → Ollama 本地模型提取 entities/preferences/facts/behaviors

定时任务（每天）：
  对所有用户记忆运行遗忘曲线
  strength = initial × e^(-λ × days_since_access)
  strength < 0.5 → 压缩内容（保留摘要）
  strength < 0.1 → 软删除

用户夸奖时：
  检测 praise 词 → 强化上一条 AI 行为记忆 strength +0.2（上限 1.0）

每周定时：
  生成用户画像（基于全部活跃记忆）
```

### 多意图顺序执行

用户说「先删除旧目录，再写入新文件，然后搜索最新资讯」，STONE 会**严格按顺序**逐步执行，每步等待工具返回结果后再决定下一步，不会跳过需要确认的步骤。

### 对话记忆

- 短期：每个 `conv_id`（飞书 `chat_id`）独立的消息窗口（默认 20 轮）
- 长期：超出窗口时 LLM 自动生成摘要，存入 SQLite，下次对话恢复
- 持久化长期记忆：提取后存入 `long_term_memory` 表，带遗忘曲线管理

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
│                                                              │
│  NoteBackend       MCPClient       EmbeddingBackend         │
│  Local/MCP      │  stdio JSON  │  sentence-transformers/   │
│                 │  -RPC 2.0    │  Ollama                   │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│                       核心层（不乐高化）                       │
│                                                              │
│   Agent (state machine)  ←→  ContextManager                 │
│         ↕                         ↕                         │
│   ToolRegistry / DryRunManager   SQLite (aiosqlite)         │
│         ↕                                                   │
│   MemoryExtractor ←→ LocalModelManager ←→ MemoryStore       │
└──────────────────────────────────────────────────────────────┘
```

### 模型路由逻辑

```
请求 → privacy_sensitive?
  ├─ 是 → Ollama (qwen2.5:14b，本地，不出网)  ← 记忆提取/压缩/画像
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
- **SSRF 防护**：HTTP Tool 阻断私有/回环 IP（10.x/172.16/192.168/127.x/169.254），DNS 失败时 fail-safe 拦截
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

# 本地 Ollama 地址（记忆提取用）
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
  "gateway": {"driver": "feishu"},
  "memory_backend": {"driver": "sqlite"},
  "sandbox": {"driver": "noop"},
  "auth_backend": {"driver": "whitelist"},
  "long_term_memory": {
    "enabled": true,
    "decay_rate": 0.05,
    "compress_threshold": 0.5,
    "forget_threshold": 0.1,
    "max_size_kb": 512
  },
  "mcp_servers": {
    "evernote": {"enabled": false, "command": "npx", "args": ["@evernote/mcp-server"]},
    "baidu_netdisk": {"enabled": false, "command": "npx", "args": ["@baiducloud/mcp-server"]}
  }
}
```

### 启动

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.2.0-dev"}
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
STONE：已创建目录 projects/stone，已写入 hello.py

你：请记住我喜欢简洁的回答风格
STONE：已记住：我喜欢简洁的回答风格

你：帮我抓取 https://example.com 的内容
STONE：[页面纯文本内容...]

你：把会议纪要保存到印象笔记
STONE：已通过印象笔记 MCP 创建笔记

你：写一个季度报告 Word 文档
STONE：已生成 report.docx，包含标题、摘要、数据表格

你：删除 projects/old_backup 目录
STONE：以下操作需要确认：
       • delete_dir: projects/old_backup
       回复「确认」执行 / 回复「取消」放弃

你：不错，就这样
STONE：好的！（已强化上一条行为记忆）
```

---

## 测试

```bash
pytest tests/ -v
# 663 tests passed
```

关键测试覆盖：

| 测试文件 | 覆盖范围 |
|----------|---------|
| `test_memory_forgetting.py` | 遗忘曲线数学正确性、压缩/删除阈值、强化逻辑、大小限制 |
| `test_memory_extractor.py` | 显式记忆检测、LLM 提取解析、表扬识别、记忆注入 |
| `test_local_model_manager.py` | embedding 后端选择、隐私强制路由、相似度排序 |
| `test_mcp_client.py` | JSON-RPC 2.0 握手、工具发现、调用分发、断线重连 |
| `test_http_tool.py` | SSRF 防护、内容类型过滤、HTML 解析、超时处理 |
| `test_note_tool.py` | 本地 CRUD、关键词路由、MCP 云端路由、搜索 |
| `test_office_tool.py` | Word/Excel/PPT 创建/读取、Markdown 转换、追加内容 |
| `test_bug_tool_dispatch.py` | 工具分发链路、正则解析、参数清洗 |
| `test_state_machine.py` | 状态机合法/非法转换 |
| `test_dry_run.py` | 危险操作确认流程 |
| `test_blackbox_*.py` | API 黑盒测试（health/chat/admin/error/contracts） |

---

## 项目结构

```
stone/
├── main.py                     # FastAPI 入口
├── config.py                   # Pydantic Settings 配置
├── stone.config.json           # 模块驱动配置
├── core/
│   ├── agent.py                # 核心状态机 + 工具分发 + 记忆钩子
│   ├── model_router.py         # 多模型路由
│   ├── context_manager.py      # 对话上下文管理
│   ├── dry_run.py              # 危险操作 dry-run 管理
│   ├── scheduler.py            # APScheduler 定时任务（含记忆衰减任务）
│   └── state_machine.py        # 状态转换验证
├── tools/                      # 工具实现
│   ├── file_tool.py
│   ├── bash_tool.py
│   ├── code_tool.py
│   ├── search_tool.py
│   ├── note_tool.py            # 本地 + MCP 云端路由
│   ├── http_tool.py            # 完整实现，SSRF 防护
│   ├── office_tool.py          # Word/Excel/PPT
│   ├── memory_tool.py          # 长期记忆操作
│   └── git_tool.py
├── modules/
│   ├── gateway/feishu.py       # 飞书 WebSocket 网关
│   ├── memory/
│   │   ├── memory_store.py     # 遗忘曲线存储
│   │   ├── memory_extractor.py # LLM 记忆提取
│   │   ├── local_model_manager.py  # 本地模型统一管理
│   │   └── embedding_backends/ # sentence-transformers / Ollama
│   ├── mcp/
│   │   ├── client.py           # MCP JSON-RPC 2.0 Client
│   │   └── process_manager.py  # MCP Server 进程生命周期
│   ├── note_backends/
│   │   ├── local_backend.py    # 本地 Markdown 笔记
│   │   └── mcp_backend.py      # 云端 MCP 后端
│   ├── interfaces/             # 所有可替换模块的 ABC 接口
│   └── sandbox/                # 代码执行沙盒
├── security/                   # Auth / AuditLogger / PromptGuard
├── models/                     # Pydantic 数据模型
├── api/                        # FastAPI 路由
├── registry/                   # 工具/技能注册表
└── tests/                      # 单元测试（663个，全部通过）
```

---

## 路线图

### Phase 2（进行中规划）
- [ ] 浏览器工具（Playwright）
- [ ] Redis 切换短期记忆
- [ ] Cloudflare Tunnel 公网接入
- [ ] 奇门遁甲工具

### Phase 3
- [ ] RAG 管道（ChromaDB + LlamaIndex）
- [ ] 向量存储 + 文档嵌入（PDF/Markdown/Word）
- [ ] Web UI 管理面板

---

## License

MIT License. See [LICENSE](LICENSE).

---

*默行者 — 沉默而高效。*

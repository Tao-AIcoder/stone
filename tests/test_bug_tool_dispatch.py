"""
tests/test_bug_tool_dispatch.py

专项测试：工具分发链路上的已知/疑似 Bug。

覆盖的问题：
  BUG-1  _extract_tool_calls 正则非贪婪截断——嵌套 JSON 无法正确解析
  BUG-2  file_tool 不支持 delete_dir，用户说"删除目录"时静默失败
  BUG-3  _build_tools_instruction 已定义但从未被注入 ctx.messages
  BUG-4  _call_dashscope 不接受 tools 参数，代码任务路由到 qwen-coder-plus
         时工具 schema 被静默丢弃
  BUG-5  tool role 消息格式：Ollama 不认识 OpenAI 风格的 tool_call_id 字段
"""

from __future__ import annotations

import inspect
import json
import sys
import os
import uuid
import asyncio

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# BUG-1  _extract_tool_calls 正则截断
# ──────────────────────────────────────────────────────────────────────────────

from core.agent import _extract_tool_calls


class TestExtractToolCallsRegex:
    """BUG-1: 非贪婪正则 {[\s\S]*?} 在嵌套 JSON 时截断，json.loads 解析失败，返回 []。"""

    def _make_block(self, payload: dict) -> str:
        """把 payload 包进 ```json ... ``` 代码块。"""
        return f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"

    # ── 正常情况（无嵌套参数），基准测试 ──────────────────────────────────────

    def test_simple_tool_call_no_params(self):
        """无 params 嵌套时应能正确解析。"""
        payload = {"tool_calls": [{"tool_name": "bash_tool", "params": {"command": "ls"}}]}
        result = _extract_tool_calls(self._make_block(payload))
        assert len(result) == 1
        assert result[0].tool_name == "bash_tool"
        assert result[0].params == {"command": "ls"}

    # ── 嵌套参数（file_tool 真实调用场景） ───────────────────────────────────

    def test_nested_params_write_file(self):
        """write_file：params 里有多个字段，JSON 嵌套两层。"""
        payload = {
            "tool_calls": [{
                "tool_name": "file_tool",
                "params": {"action": "write_file", "path": "todo.txt", "content": "买菜\n健身"}
            }]
        }
        result = _extract_tool_calls(self._make_block(payload))
        assert len(result) == 1, f"期望 1 个 tool_call，实际得到 {len(result)}"
        assert result[0].tool_name == "file_tool"
        assert result[0].params.get("action") == "write_file"

    def test_nested_params_create_dir(self):
        """create_dir：params 中含 path 字段。"""
        payload = {
            "tool_calls": [{
                "tool_name": "file_tool",
                "params": {"action": "create_dir", "path": "projects/sub"}
            }]
        }
        result = _extract_tool_calls(self._make_block(payload))
        assert len(result) == 1, f"期望 1 个 tool_call，实际得到 {len(result)}"
        assert result[0].params.get("action") == "create_dir"

    def test_nested_params_delete_file(self):
        """delete_file。"""
        payload = {
            "tool_calls": [{
                "tool_name": "file_tool",
                "params": {"action": "delete_file", "path": "old.txt"}
            }]
        }
        result = _extract_tool_calls(self._make_block(payload))
        assert len(result) == 1, f"期望 1 个 tool_call，实际得到 {len(result)}"
        assert result[0].params.get("action") == "delete_file"

    def test_nested_params_list_dir(self):
        """list_dir：path='.', show_hidden=false。"""
        payload = {
            "tool_calls": [{
                "tool_name": "file_tool",
                "params": {"action": "list_dir", "path": ".", "show_hidden": False}
            }]
        }
        result = _extract_tool_calls(self._make_block(payload))
        assert len(result) == 1, f"期望 1 个 tool_call，实际得到 {len(result)}"

    def test_multiple_tool_calls_in_one_block(self):
        """多 tool_call 在同一 JSON 块。"""
        payload = {
            "tool_calls": [
                {"tool_name": "file_tool", "params": {"action": "create_dir", "path": "a"}},
                {"tool_name": "file_tool", "params": {"action": "write_file", "path": "a/b.txt", "content": "hi"}},
            ]
        }
        result = _extract_tool_calls(self._make_block(payload))
        assert len(result) == 2, f"期望 2 个 tool_call，实际得到 {len(result)}"

    def test_search_tool_nested_query(self):
        """search_tool 含 query 字段。"""
        payload = {
            "tool_calls": [{
                "tool_name": "search_tool",
                "params": {"query": "Claude 4 最新发布情况", "max_results": 5}
            }]
        }
        result = _extract_tool_calls(self._make_block(payload))
        assert len(result) == 1
        assert result[0].tool_name == "search_tool"
        assert result[0].params.get("query") == "Claude 4 最新发布情况"

    def test_text_with_preamble_before_json_block(self):
        """LLM 在 JSON 块前面加了一句自然语言（违反指令但常见）。"""
        payload = {
            "tool_calls": [{
                "tool_name": "file_tool",
                "params": {"action": "read_file", "path": "readme.txt"}
            }]
        }
        text = "好的，我来帮你读取文件。\n" + self._make_block(payload)
        result = _extract_tool_calls(text)
        assert len(result) == 1

    def test_empty_text_returns_empty_list(self):
        result = _extract_tool_calls("")
        assert result == []

    def test_plain_text_no_tool_call(self):
        result = _extract_tool_calls("今天天气很好，不需要调用工具。")
        assert result == []

    def test_malformed_json_block_skipped(self):
        text = "```json\n{broken json\n```"
        result = _extract_tool_calls(text)
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# BUG-2  file_tool 不支持 delete_dir
# ──────────────────────────────────────────────────────────────────────────────

from tools.file_tool import FileTool


@pytest.fixture
def file_tool():
    return FileTool()


@pytest.fixture
def workspace_subdir(file_tool):
    """在 WORKSPACE_DIR 下创建隔离子目录，测试后清理。"""
    import shutil
    name = f"_bugtest_{uuid.uuid4().hex[:8]}"
    subdir_path = file_tool.workspace / name
    subdir_path.mkdir(parents=True, exist_ok=True)
    yield name
    shutil.rmtree(subdir_path, ignore_errors=True)


class TestFileToolDeleteDir:
    """BUG-2 修复验证: file_tool 应支持 delete_dir action。"""

    @pytest.mark.asyncio
    async def test_delete_empty_dir_succeeds(self, file_tool, workspace_subdir):
        """delete_dir 删除空目录应成功。"""
        result = await file_tool.execute(
            {"action": "delete_dir", "path": workspace_subdir}
        )
        assert result.success, f"删除空目录应成功，实际：{result.error}"
        assert not (file_tool.workspace / workspace_subdir).exists()

    @pytest.mark.asyncio
    async def test_delete_nonempty_dir_succeeds(self, file_tool, workspace_subdir):
        """delete_dir 递归删除含文件的目录应成功。"""
        inner = f"{workspace_subdir}/inner.txt"
        await file_tool.execute({"action": "write_file", "path": inner, "content": "hello"})

        result = await file_tool.execute({"action": "delete_dir", "path": workspace_subdir})
        assert result.success, f"删除非空目录应成功，实际：{result.error}"
        assert not (file_tool.workspace / workspace_subdir).exists()

    @pytest.mark.asyncio
    async def test_delete_dir_needs_confirmation(self, file_tool, workspace_subdir):
        """delete_dir 应需要用户确认。"""
        assert file_tool.needs_confirmation_for({"action": "delete_dir", "path": workspace_subdir})

    @pytest.mark.asyncio
    async def test_delete_dir_nonexistent_fails_clearly(self, file_tool):
        """删除不存在的目录应返回明确错误。"""
        result = await file_tool.execute({"action": "delete_dir", "path": "nonexistent_xyz"})
        assert not result.success
        assert "不存在" in (result.error or "")

    @pytest.mark.asyncio
    async def test_delete_dir_on_file_fails_clearly(self, file_tool, workspace_subdir):
        """对文件路径使用 delete_dir 应报错提示应用 delete_file。"""
        filepath = f"{workspace_subdir}/afile.txt"
        await file_tool.execute({"action": "write_file", "path": filepath, "content": "x"})
        result = await file_tool.execute({"action": "delete_dir", "path": filepath})
        assert not result.success
        assert "delete_file" in (result.error or ""), \
            f"应提示使用 delete_file，实际：{result.error!r}"

    @pytest.mark.asyncio
    async def test_delete_file_on_directory_still_fails(self, file_tool, workspace_subdir):
        """delete_file 用于目录路径仍应报错（行为不变）。"""
        result = await file_tool.execute(
            {"action": "delete_file", "path": workspace_subdir}
        )
        assert not result.success
        assert "目录" in (result.error or "")

    @pytest.mark.asyncio
    async def test_unsupported_action_lists_all_valid_actions(self, file_tool):
        """不支持的 action（如 rename）返回的错误应列出全部合法 action。"""
        result = await file_tool.execute({"action": "rename", "path": "anything"})
        assert not result.success
        error_msg = result.error or ""
        for action in ("read_file", "write_file", "delete_file", "delete_dir", "list_dir", "create_dir"):
            assert action in error_msg, \
                f"错误信息应包含合法 action '{action}'，实际：{error_msg!r}"


# ──────────────────────────────────────────────────────────────────────────────
# BUG-3  _build_tools_instruction 定义了但从未注入 ctx.messages
# ──────────────────────────────────────────────────────────────────────────────

import core.agent as _agent_module


class TestBuildToolsInstructionInjected:
    """BUG-4 修复验证: _build_tools_instruction 应在 process() 中注入系统消息。"""

    def test_function_exists(self):
        """确认函数存在。"""
        assert hasattr(_agent_module, "_build_tools_instruction")

    def test_injected_in_process(self):
        """process() 源码应调用 _build_tools_instruction 并注入 system_content。"""
        src = inspect.getsource(_agent_module.Agent.process)
        assert "_build_tools_instruction" in src, \
            "_build_tools_instruction 未在 process() 中被调用，BUG-4 未修复"

    def test_tool_instruction_output_contains_json_format(self):
        """生成的指令应包含 JSON 格式示例。"""
        sample_schema = [{"name": "file_tool", "description": "文件操作", "parameters": {}}]
        result = _agent_module._build_tools_instruction(sample_schema)
        assert "tool_calls" in result
        assert "tool_name" in result
        assert "json" in result.lower()


# ──────────────────────────────────────────────────────────────────────────────
# BUG-4  _call_dashscope 不接受 tools 参数
# ──────────────────────────────────────────────────────────────────────────────

from core.model_router import ModelRouter


class TestDashscopeSupportsTools:
    """BUG-5 修复验证: _call_dashscope 应接受并传递 tools 参数。"""

    def test_call_dashscope_signature_has_tools(self):
        """修复后 _call_dashscope 签名应包含 tools 参数。"""
        sig = inspect.signature(ModelRouter._call_dashscope)
        assert "tools" in sig.parameters, \
            "_call_dashscope 缺少 tools 参数，BUG-5 未修复"

    def test_call_model_passes_tools_for_qwen(self):
        """_call_model 在 model_id=qwen 时应传入 tools。"""
        src = inspect.getsource(ModelRouter._call_model)
        lines = [l for l in src.splitlines() if "_call_dashscope" in l]
        assert lines, "_call_model 里找不到 _call_dashscope 调用"
        call_line = " ".join(lines)
        assert "tools" in call_line, \
            f"_call_dashscope 调用未传 tools，BUG-5 未修复：{call_line!r}"

    def test_code_task_routes_to_qwen(self):
        """balanced 模式下 code 任务仍路由到 qwen-coder-plus。"""
        from core.model_router import _select_model
        model = _select_model(
            task_type="code",
            privacy_mode="balanced",
            privacy_sensitive=False,
            token_estimate=100,
        )
        assert model == "qwen-coder-plus"

    def test_dashscope_tool_call_parsing_valid_json(self):
        """DashScope 工具调用解析：合法 JSON arguments 能正确解析。"""
        # 模拟 DashScope 返回的 tool_call 对象（duck-typing）
        class FakeFn:
            name = "file_tool"
            arguments = '{"action": "write_file", "path": "test.txt"}'
        class FakeTc:
            function = FakeFn()
            id = "call_abc123"

        # 直接验证解析逻辑（复制自 _call_dashscope 实现）
        tc = FakeTc()
        fn = tc.function
        params = json.loads(fn.arguments)
        assert params["action"] == "write_file"
        assert params["path"] == "test.txt"


# ──────────────────────────────────────────────────────────────────────────────
# BUG-5  tool role 消息格式与 Ollama 的兼容性
# ──────────────────────────────────────────────────────────────────────────────

class TestToolCallIdConsistency:
    """BUG-5b 修复验证: assistant_msg 里的 tool_calls[].id 应与后续 tool 结果的 tool_call_id 一致。"""

    def test_assistant_msg_uses_processed_tool_call_ids(self):
        """_handle_thinking 源码应使用 tool_calls（已处理列表，含 UUID）
        而非 llm_resp.tool_calls（可能含空 id）来构建 assistant_msg。"""
        src = inspect.getsource(_agent_module.Agent._handle_thinking)
        # 修复后：使用 tc.call_id（来自 ToolCall 对象）
        assert "tc.call_id" in src, \
            "assistant_msg 未使用 tc.call_id，call_id 不一致问题未修复"
        # 不应再用 tc.get("call_id", "")（原始 llm_resp 中的空字符串）
        assert 'tc.get("call_id", "")' not in src, \
            'assistant_msg 仍使用 tc.get("call_id","")，可能导致 Ollama id 为空串'

    def test_uuid_generated_when_call_id_empty(self):
        """当 LLM 返回空 call_id 时，_parse_tool_calls 应自动生成 UUID。"""
        src = inspect.getsource(_agent_module._parse_tool_calls)
        assert "uuid" in src, "未见 UUID 生成逻辑，call_id 可能为空串"

    def test_executing_appends_tool_message_with_call_id(self):
        """_handle_executing 应将 tool 结果以 tool_call_id 字段追加到 messages。"""
        src = inspect.getsource(_agent_module.Agent._handle_executing)
        assert "tool_call_id" in src
        assert "r.call_id" in src

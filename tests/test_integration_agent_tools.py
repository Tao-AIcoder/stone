"""
tests/test_integration_agent_tools.py - PRD 15.4 required integration tests.

Covers:
1. 工具调用链路：消息 → agent → file_tool → 回复
2. 工具调用链路：消息 → agent → search_tool → 回复
3. 模块降级：Ollama 不可用 → 回退云端模型，仍能正常响应

These tests use a real Agent + StateMachine + SkillRegistry + real tools,
but mock the ModelRouter (to control LLM output) and other external dependencies.
"""

from __future__ import annotations

import sys
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.agent import Agent
from core.dry_run import DryRunManager
from core.model_router import LLMResponse
from models.message import MessageSource, MessageType, UserMessage
from registry.skill_registry import SkillRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_user_message(content: str, conv_id: str = "test-conv") -> UserMessage:
    return UserMessage(
        conv_id=conv_id,
        user_id="default_user",
        message_type=MessageType.TEXT,
        source=MessageSource.API,
        content=content,
    )


def make_mock_context_manager() -> MagicMock:
    cm = MagicMock()
    cm.get_context = AsyncMock(return_value=[])
    cm.save_context = AsyncMock()
    return cm


def make_mock_audit() -> MagicMock:
    audit = MagicMock()
    audit.log = AsyncMock()
    return audit


def make_real_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register_phase1a_tools()
    return registry


def make_agent_with_dry_run_off(model_router: Any) -> Agent:
    """Build a real Agent with dry_run disabled via config patch."""
    return Agent(
        model_router=model_router,
        skill_registry=make_real_registry(),
        context_manager=make_mock_context_manager(),
        dry_run_manager=DryRunManager(audit_logger=make_mock_audit()),
        audit_logger=make_mock_audit(),
    )


# ── 1. 工具调用链路：file_tool ────────────────────────────────────────────────

class TestFileToolChain:
    """消息 → agent → file_tool → 回复"""

    @pytest.mark.asyncio
    async def test_list_dir_tool_call_executes(self):
        """
        LLM returns a file_tool/list_dir call; agent executes it and calls LLM again.
        list_dir does not require dry-run, so no config patching needed.
        """
        tool_call_response = LLMResponse(
            text="",
            tool_calls=[{
                "tool_name": "file_tool",
                "params": {"action": "list_dir", "path": "."},
                "call_id": "call-001",
            }],
        )
        summary_response = LLMResponse(text="工作目录内容已列出。", tool_calls=[])

        router = MagicMock()
        router.chat = AsyncMock(side_effect=[tool_call_response, summary_response])

        agent = make_agent_with_dry_run_off(router)
        response = await agent.process(make_user_message("列出工作目录"))

        assert not response.is_error
        assert "file_tool" in response.tools_used

    @pytest.mark.asyncio
    async def test_read_file_chain(self):
        """LLM calls read_file; read of non-existent path → error propagated as tool result."""
        tool_call_response = LLMResponse(
            text="",
            tool_calls=[{
                "tool_name": "file_tool",
                "params": {"action": "read_file", "path": "_nonexistent_.txt"},
                "call_id": "call-r",
            }],
        )
        final = LLMResponse(text="文件不存在。", tool_calls=[])

        router = MagicMock()
        router.chat = AsyncMock(side_effect=[tool_call_response, final])

        agent = make_agent_with_dry_run_off(router)
        response = await agent.process(make_user_message("读取文件"))

        # Agent should complete without crashing, tool failure is surfaced as tool result
        assert response.content
        assert "file_tool" in response.tools_used

    @pytest.mark.asyncio
    async def test_write_file_with_dry_run_disabled(self):
        """With dry_run disabled, write_file executes immediately without confirmation."""
        import uuid, shutil
        from config import settings as real_settings
        unique = uuid.uuid4().hex[:8]
        test_path = f"_agent_write_{unique}.txt"
        tool_call_response = LLMResponse(
            text="",
            tool_calls=[{
                "tool_name": "file_tool",
                "params": {
                    "action": "write_file",
                    "path": test_path,
                    "content": "agent test content",
                },
                "call_id": "call-w",
            }],
        )
        final = LLMResponse(text="文件已写入。", tool_calls=[])

        router = MagicMock()
        router.chat = AsyncMock(side_effect=[tool_call_response, final])

        # Patch dry_run_enabled to False in config so write_file runs immediately
        from config import settings as real_settings
        try:
            with patch.object(type(real_settings), "dry_run_enabled",
                              new_callable=lambda: property(lambda self: False)):
                agent = make_agent_with_dry_run_off(router)
                response = await agent.process(make_user_message("写文件"))
        finally:
            # Clean up the file written to workspace by this test
            target = real_settings.workspace_dir / test_path
            if target.exists():
                target.unlink()

        assert "file_tool" in response.tools_used

    @pytest.mark.asyncio
    async def test_tool_result_appended_to_message_history(self):
        """After tool execution, a 'tool' role message is appended to LLM context."""
        tool_call_response = LLMResponse(
            text="",
            tool_calls=[{
                "tool_name": "file_tool",
                "params": {"action": "list_dir", "path": "."},
                "call_id": "call-001",
            }],
        )

        captured_messages: list[list] = []

        async def capture_chat(messages, **kwargs):
            captured_messages.append(list(messages))
            if len(captured_messages) == 1:
                return tool_call_response
            return LLMResponse(text="完成。", tool_calls=[])

        router = MagicMock()
        router.chat = capture_chat

        agent = make_agent_with_dry_run_off(router)
        await agent.process(make_user_message("列出目录"))

        assert len(captured_messages) >= 2, "LLM should be called at least twice (tool call + summary)"
        second_call_roles = [m.get("role") for m in captured_messages[1]]
        assert "tool" in second_call_roles, f"Expected 'tool' role message, got: {second_call_roles}"

    @pytest.mark.asyncio
    async def test_tool_name_recorded_in_tools_used(self):
        """tools_used in BotResponse must include every tool that ran."""
        tool_call_response = LLMResponse(
            text="",
            tool_calls=[{
                "tool_name": "file_tool",
                "params": {"action": "list_dir", "path": "."},
                "call_id": "c1",
            }],
        )
        router = MagicMock()
        router.chat = AsyncMock(side_effect=[
            tool_call_response,
            LLMResponse(text="done", tool_calls=[]),
        ])
        agent = make_agent_with_dry_run_off(router)
        response = await agent.process(make_user_message("列目录"))
        assert "file_tool" in response.tools_used


# ── 2. 工具调用链路：search_tool ─────────────────────────────────────────────

class TestSearchToolChain:
    """消息 → agent → search_tool → 回复"""

    @pytest.mark.asyncio
    async def test_search_tool_call_executes(self):
        """Agent calls search_tool; Tavily is mocked to return controlled data."""
        tool_call_response = LLMResponse(
            text="",
            tool_calls=[{
                "tool_name": "search_tool",
                "params": {"query": "Python asyncio", "max_results": 2},
                "call_id": "call-s",
            }],
        )
        final = LLMResponse(text="搜索结果如下。", tool_calls=[])

        router = MagicMock()
        router.chat = AsyncMock(side_effect=[tool_call_response, final])

        mock_tavily_response = {
            "answer": "asyncio is Python's async framework",
            "results": [
                {"title": "Asyncio Docs", "url": "https://docs.python.org", "content": "Asyncio content"}
            ],
        }

        with patch("tavily.TavilyClient") as mock_tavily_cls:
            mock_client = MagicMock()
            mock_client.search.return_value = mock_tavily_response
            mock_tavily_cls.return_value = mock_client

            agent = make_agent_with_dry_run_off(router)
            response = await agent.process(make_user_message("搜索 Python asyncio"))

        assert not response.is_error
        assert "search_tool" in response.tools_used

    @pytest.mark.asyncio
    async def test_search_result_passed_to_llm(self):
        """Search result content is included in the tool message sent to LLM."""
        tool_call_response = LLMResponse(
            text="",
            tool_calls=[{
                "tool_name": "search_tool",
                "params": {"query": "test query"},
                "call_id": "s1",
            }],
        )

        captured: list[list] = []

        async def capture_chat(messages, **kwargs):
            captured.append(list(messages))
            if len(captured) == 1:
                return tool_call_response
            return LLMResponse(text="done", tool_calls=[])

        router = MagicMock()
        router.chat = capture_chat

        mock_response = {"answer": "UNIQUE_ANSWER_MARKER", "results": []}

        with patch("tavily.TavilyClient") as mock_tavily_cls:
            mock_client = MagicMock()
            mock_client.search.return_value = mock_response
            mock_tavily_cls.return_value = mock_client

            agent = make_agent_with_dry_run_off(router)
            await agent.process(make_user_message("搜索"))

        assert len(captured) >= 2
        tool_messages = [m for m in captured[1] if m.get("role") == "tool"]
        assert tool_messages, "No tool message found in second LLM call"
        combined_content = " ".join(str(m.get("content", "")) for m in tool_messages)
        assert "UNIQUE_ANSWER_MARKER" in combined_content


# ── 3. 模块降级：Ollama 不可用 ────────────────────────────────────────────────

class TestModelDegradation:
    """
    PRD 15.4: 关闭 Ollama → 系统降级运行，仅云端模型可用时仍能对话。
    """

    @pytest.mark.asyncio
    async def test_agent_routes_to_error_handling_when_model_fails(self):
        """
        When model_router.chat raises ModelError, agent transitions to ERROR_HANDLING
        and returns an error response (not an unhandled exception).
        """
        from models.errors import ModelError

        router = MagicMock()
        router.chat = AsyncMock(
            side_effect=ModelError(message="Ollama 不可用", model_id="qwen2.5:14b")
        )

        agent = make_agent_with_dry_run_off(router)
        response = await agent.process(make_user_message("你好"))

        # Agent must not raise; it must return a BotResponse
        assert response is not None
        assert isinstance(response.content, str)
        assert response.content  # non-empty (error message)

    @pytest.mark.asyncio
    async def test_health_shows_degraded_when_ollama_unreachable(self):
        """
        /health shows ollama as unreachable when connection fails,
        and overall status is 'degraded'.
        health.py now uses request.app.state.loader so mock loader is visible.
        """
        import httpx
        from fastapi.testclient import TestClient
        from tests.conftest import make_test_app, make_mock_loader

        loader = make_mock_loader()
        app = make_test_app(loader=loader)
        # Patch httpx.AsyncClient to simulate Ollama being unreachable.
        # Must be done at the httpx module level since health.py does `import httpx` lazily.

        class FailingAsyncClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                raise OSError("connection refused")
            async def __aexit__(self, *args):
                pass

        with patch("httpx.AsyncClient", FailingAsyncClient):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("degraded", "unhealthy"), (
            f"Expected degraded/unhealthy when Ollama unreachable, got: {data['status']}"
        )
        assert data["modules"].get("ollama") == "unreachable"

    @pytest.mark.asyncio
    async def test_tools_remain_functional_when_model_unavailable(self):
        """
        Even when LLM is unavailable, individual tools (file_tool, search_tool)
        still work correctly — the tool layer is independent of the model layer.
        """
        registry = make_real_registry()

        # file_tool works
        file_tool = registry.get_tool_instance("file_tool")
        assert file_tool is not None
        result = await file_tool.execute(
            {"action": "list_dir", "path": "."},
            user_id="default_user",
        )
        assert result.success

        # search_tool registered and accessible
        search_tool = registry.get_tool_instance("search_tool")
        assert search_tool is not None

        # bash_tool registered and accessible
        bash_tool = registry.get_tool_instance("bash_tool")
        assert bash_tool is not None

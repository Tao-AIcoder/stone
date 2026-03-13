"""
tests/test_agent.py - Integration test skeleton for STONE agent.

These tests use mocked dependencies to verify agent logic without
requiring running LLMs, Feishu connections, or a real database.
"""

from __future__ import annotations

import sys
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.agent_state import AgentContext, AgentState
from models.message import BotResponse, MessageSource, MessageType, UserMessage


# ── Mock Factories ────────────────────────────────────────────────────────────

def make_mock_model_router(response: str = "Test response") -> AsyncMock:
    router = AsyncMock()
    router.chat = AsyncMock(return_value=response)
    return router


def make_mock_skill_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_tools_schema.return_value = []
    registry.get_tool.return_value = None
    registry.get_tool_instance.return_value = None
    registry.list_tools.return_value = []
    return registry


def make_mock_context_manager() -> AsyncMock:
    cm = AsyncMock()
    cm.get_context = AsyncMock(return_value=[])
    cm.save_context = AsyncMock()
    return cm


def make_mock_dry_run_manager() -> AsyncMock:
    drm = AsyncMock()
    drm.has_pending.return_value = False
    drm.generate_plan = AsyncMock(return_value={"steps": [], "total_steps": 0})
    drm.format_preview.return_value = "操作预览"
    return drm


def make_mock_audit_logger() -> AsyncMock:
    audit = AsyncMock()
    audit.log = AsyncMock()
    audit.log_security = AsyncMock()
    return audit


def make_user_message(content: str = "hello") -> UserMessage:
    return UserMessage(
        user_id="test_user",
        message_type=MessageType.TEXT,
        source=MessageSource.API,
        content=content,
    )


# ── Agent Tests ───────────────────────────────────────────────────────────────

class TestAgentProcess:
    @pytest.mark.asyncio
    async def test_simple_text_response(self) -> None:
        """Agent should return a BotResponse for a simple text query."""
        from core.agent import Agent

        agent = Agent(
            model_router=make_mock_model_router("你好！我是默行者。"),
            skill_registry=make_mock_skill_registry(),
            context_manager=make_mock_context_manager(),
            dry_run_manager=make_mock_dry_run_manager(),
            audit_logger=make_mock_audit_logger(),
        )

        msg = make_user_message("你好")
        response = await agent.process(msg)

        assert isinstance(response, BotResponse)
        assert response.content != ""
        assert response.is_error is False

    @pytest.mark.asyncio
    async def test_response_contains_user_message_echo(self) -> None:
        """The model router receives the user message."""
        from core.agent import Agent

        router = make_mock_model_router("这是回复")
        agent = Agent(
            model_router=router,
            skill_registry=make_mock_skill_registry(),
            context_manager=make_mock_context_manager(),
            dry_run_manager=make_mock_dry_run_manager(),
            audit_logger=make_mock_audit_logger(),
        )

        msg = make_user_message("具体问题内容")
        await agent.process(msg)

        # Model router should have been called with messages containing user content
        router.chat.assert_called_once()
        call_args = router.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        all_content = " ".join(str(m.get("content", "")) for m in messages)
        assert "具体问题内容" in all_content

    @pytest.mark.asyncio
    async def test_model_error_returns_error_response(self) -> None:
        """When model fails, agent should return a graceful error response."""
        from core.agent import Agent
        from models.errors import ModelError

        router = AsyncMock()
        router.chat = AsyncMock(side_effect=ModelError("模型不可用", model_id="test"))

        agent = Agent(
            model_router=router,
            skill_registry=make_mock_skill_registry(),
            context_manager=make_mock_context_manager(),
            dry_run_manager=make_mock_dry_run_manager(),
            audit_logger=make_mock_audit_logger(),
        )

        msg = make_user_message("test error handling")
        response = await agent.process(msg)

        # Should not raise, should return an error response
        assert isinstance(response, BotResponse)
        # Content should mention the error
        assert response.content != ""

    @pytest.mark.asyncio
    async def test_conv_id_preserved_in_response(self) -> None:
        """Response conv_id should match request conv_id."""
        from core.agent import Agent

        agent = Agent(
            model_router=make_mock_model_router("ok"),
            skill_registry=make_mock_skill_registry(),
            context_manager=make_mock_context_manager(),
            dry_run_manager=make_mock_dry_run_manager(),
            audit_logger=make_mock_audit_logger(),
        )

        msg = make_user_message("hello")
        msg.conv_id = "test-conv-123"
        response = await agent.process(msg)

        assert response.conv_id == "test-conv-123"

    @pytest.mark.asyncio
    async def test_user_id_preserved_in_response(self) -> None:
        """Response user_id should match request user_id."""
        from core.agent import Agent

        agent = Agent(
            model_router=make_mock_model_router("ok"),
            skill_registry=make_mock_skill_registry(),
            context_manager=make_mock_context_manager(),
            dry_run_manager=make_mock_dry_run_manager(),
            audit_logger=make_mock_audit_logger(),
        )

        msg = make_user_message("hello")
        msg.user_id = "special_user_42"
        response = await agent.process(msg)

        assert response.user_id == "special_user_42"

    @pytest.mark.asyncio
    async def test_audit_log_called_on_process(self) -> None:
        """AuditLogger.log should be called after processing."""
        from core.agent import Agent

        audit = make_mock_audit_logger()
        agent = Agent(
            model_router=make_mock_model_router("response"),
            skill_registry=make_mock_skill_registry(),
            context_manager=make_mock_context_manager(),
            dry_run_manager=make_mock_dry_run_manager(),
            audit_logger=audit,
        )

        msg = make_user_message("test audit")
        await agent.process(msg)

        audit.log.assert_called()


# ── Tool Call Parsing Tests ───────────────────────────────────────────────────

class TestToolCallParsing:
    def test_parse_json_tool_call(self) -> None:
        from core.agent import _extract_tool_calls

        llm_output = '''
        I will search for information.
        ```json
        {"tool_calls": [{"tool_name": "search_tool", "params": {"query": "python asyncio"}}]}
        ```
        '''
        calls = _extract_tool_calls(llm_output)
        assert len(calls) == 1
        assert calls[0].tool_name == "search_tool"
        assert calls[0].params["query"] == "python asyncio"

    def test_parse_multiple_tool_calls(self) -> None:
        from core.agent import _extract_tool_calls

        llm_output = '''
        ```json
        {"tool_calls": [
            {"tool_name": "bash_tool", "params": {"command": "ls"}},
            {"tool_name": "file_tool", "params": {"action": "read_file", "path": "test.txt"}}
        ]}
        ```
        '''
        calls = _extract_tool_calls(llm_output)
        assert len(calls) == 2
        assert calls[0].tool_name == "bash_tool"
        assert calls[1].tool_name == "file_tool"

    def test_no_tool_call_returns_empty(self) -> None:
        from core.agent import _extract_tool_calls

        llm_output = "This is just a text response without any tool calls."
        calls = _extract_tool_calls(llm_output)
        assert calls == []

    def test_invalid_json_returns_empty(self) -> None:
        from core.agent import _extract_tool_calls

        llm_output = "```json\n{invalid json here}\n```"
        calls = _extract_tool_calls(llm_output)
        assert calls == []

    def test_each_call_has_unique_call_id(self) -> None:
        from core.agent import _extract_tool_calls

        llm_output = '''
        ```json
        {"tool_calls": [
            {"tool_name": "bash_tool", "params": {"command": "ls"}},
            {"tool_name": "bash_tool", "params": {"command": "pwd"}}
        ]}
        ```
        '''
        calls = _extract_tool_calls(llm_output)
        assert len(calls) == 2
        assert calls[0].call_id != calls[1].call_id

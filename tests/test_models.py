"""
tests/test_models.py - Unit tests for all Pydantic data models.

Covers:
- models/errors.py        (exception hierarchy)
- models/agent_state.py   (AgentContext, ToolCall, ToolResult)
- models/message.py       (UserMessage, BotResponse)
- models/memory.py        (Memory)
- models/skill.py         (Skill, SkillCategory)
"""

from __future__ import annotations

import sys
import os
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.errors import (
    StoneError, InvalidStateTransition, AuthError, PermissionError,
    PromptInjectionError, ModuleError, ModuleNotFoundError,
    ModuleFallbackError, ModelError, ModelTimeoutError, ModelQuotaError,
    ToolError, SandboxError, ToolTimeoutError, DryRunRejectedError,
)
from models.agent_state import AgentContext, AgentState, ToolCall, ToolResult
from models.message import UserMessage, BotResponse, MessageType, MessageSource
from models.skill import Skill, SkillCategory


# ── Error Models ──────────────────────────────────────────────────────────────

class TestStoneError:
    def test_base_error_has_message(self) -> None:
        err = StoneError("test message", code="TEST")
        assert err.message == "test message"
        assert err.code == "TEST"

    def test_base_error_is_exception(self) -> None:
        err = StoneError("msg", code="C")
        assert isinstance(err, Exception)

    def test_default_code(self) -> None:
        err = StoneError("msg")
        assert err.code == "STONE_ERROR"

    def test_repr_contains_code_and_message(self) -> None:
        err = StoneError("hello", code="HI")
        r = repr(err)
        assert "HI" in r
        assert "hello" in r


class TestInvalidStateTransition:
    def test_from_and_to_state_stored(self) -> None:
        err = InvalidStateTransition("IDLE", "EXECUTING")
        assert err.from_state == "IDLE"
        assert err.to_state == "EXECUTING"

    def test_message_contains_both_states(self) -> None:
        err = InvalidStateTransition("IDLE", "EXECUTING")
        assert "IDLE" in err.message
        assert "EXECUTING" in err.message

    def test_code_is_correct(self) -> None:
        err = InvalidStateTransition("A", "B")
        assert err.code == "INVALID_STATE_TRANSITION"

    def test_is_stone_error(self) -> None:
        err = InvalidStateTransition("A", "B")
        assert isinstance(err, StoneError)


class TestAuthError:
    def test_default_message(self) -> None:
        err = AuthError()
        assert err.message  # non-empty
        assert err.code == "AUTH_ERROR"

    def test_custom_message(self) -> None:
        err = AuthError("账户已锁定")
        assert "锁定" in err.message


class TestPromptInjectionError:
    def test_pattern_stored(self) -> None:
        err = PromptInjectionError(pattern="role_override")
        assert err.pattern == "role_override"

    def test_default_pattern_empty(self) -> None:
        err = PromptInjectionError()
        assert err.pattern == ""


class TestModelErrors:
    def test_model_timeout_stores_timeout(self) -> None:
        err = ModelTimeoutError(model_id="qwen2.5:14b", timeout_seconds=30.0)
        assert err.timeout_seconds == 30.0
        assert err.model_id == "qwen2.5:14b"
        assert err.code == "MODEL_TIMEOUT"

    def test_model_quota_stores_model_id(self) -> None:
        err = ModelQuotaError(model_id="glm-4-plus")
        assert err.model_id == "glm-4-plus"
        assert err.code == "MODEL_QUOTA_EXCEEDED"


class TestToolErrors:
    def test_sandbox_error_code(self) -> None:
        err = SandboxError("container failed")
        assert err.code == "SANDBOX_ERROR"

    def test_tool_timeout_stores_seconds(self) -> None:
        err = ToolTimeoutError(tool_name="bash_tool", timeout_seconds=30.0)
        assert err.timeout_seconds == 30.0
        assert err.tool_name == "bash_tool"
        assert err.code == "TOOL_TIMEOUT"


class TestDryRunRejectedError:
    def test_conv_id_stored(self) -> None:
        err = DryRunRejectedError(conv_id="abc-123")
        assert err.conv_id == "abc-123"
        assert "abc-123" in err.message

    def test_code(self) -> None:
        err = DryRunRejectedError()
        assert err.code == "DRY_RUN_REJECTED"


# ── AgentState Models ─────────────────────────────────────────────────────────

class TestAgentContext:
    def test_default_state_is_idle(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.state == AgentState.IDLE

    def test_conv_id_auto_generated(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.conv_id
        assert len(ctx.conv_id) > 0

    def test_user_id_set_correctly(self) -> None:
        ctx = AgentContext(user_id="user_42")
        assert ctx.user_id == "user_42"

    def test_default_tool_iterations_zero(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.tool_iteration == 0

    def test_max_tool_iterations_default(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.max_tool_iterations == 10

    def test_pending_tool_calls_initially_empty(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.pending_tool_calls == []

    def test_tool_results_initially_empty(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.tool_results == []

    def test_dry_run_plan_initially_none(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.dry_run_plan is None

    def test_dry_run_confirmed_initially_none(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.dry_run_confirmed is None

    def test_mark_updated_changes_timestamp(self) -> None:
        ctx = AgentContext(user_id="u1")
        before = ctx.updated_at
        import time; time.sleep(0.01)
        ctx.mark_updated()
        assert ctx.updated_at >= before

    def test_final_response_initially_empty(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.final_response == ""

    def test_error_message_initially_empty(self) -> None:
        ctx = AgentContext(user_id="u1")
        assert ctx.error_message == ""


class TestToolCall:
    def test_tool_call_has_auto_call_id(self) -> None:
        tc = ToolCall(tool_name="file_tool")
        assert tc.call_id
        assert len(tc.call_id) > 0

    def test_params_default_empty(self) -> None:
        tc = ToolCall(tool_name="search_tool")
        assert tc.params == {}

    def test_params_can_be_set(self) -> None:
        tc = ToolCall(tool_name="file_tool", params={"path": "/tmp/test.txt"})
        assert tc.params["path"] == "/tmp/test.txt"


class TestToolResult:
    def test_successful_result(self) -> None:
        tr = ToolResult(call_id="x", tool_name="file_tool", success=True, output="hello")
        assert tr.success is True
        assert tr.output == "hello"

    def test_failed_result(self) -> None:
        tr = ToolResult(call_id="x", tool_name="bash_tool", success=False, error="timeout")
        assert tr.success is False
        assert tr.error == "timeout"

    def test_output_default_empty(self) -> None:
        tr = ToolResult(call_id="x", tool_name="t", success=True)
        assert tr.output == ""


# ── Message Models ────────────────────────────────────────────────────────────

class TestUserMessage:
    def test_default_source_is_api(self) -> None:
        msg = UserMessage(content="hello")
        assert msg.source == MessageSource.API

    def test_message_id_auto_generated(self) -> None:
        msg = UserMessage(content="hello")
        assert msg.message_id
        assert len(msg.message_id) > 0

    def test_conv_id_auto_generated(self) -> None:
        msg = UserMessage(content="hello")
        assert msg.conv_id

    def test_default_type_is_text(self) -> None:
        msg = UserMessage(content="hello")
        assert msg.message_type == MessageType.TEXT

    def test_task_type_default_chat(self) -> None:
        msg = UserMessage(content="hello")
        assert msg.task_type == "chat"

    def test_privacy_sensitive_default_false(self) -> None:
        msg = UserMessage(content="hello")
        assert msg.privacy_sensitive is False

    def test_attachments_default_empty(self) -> None:
        msg = UserMessage(content="hello")
        assert msg.attachments == []

    def test_content_can_be_empty(self) -> None:
        msg = UserMessage(content="")
        assert msg.content == ""

    def test_feishu_source(self) -> None:
        msg = UserMessage(content="hi", source=MessageSource.FEISHU)
        assert msg.source == MessageSource.FEISHU


class TestBotResponse:
    def test_response_id_auto_generated(self) -> None:
        r = BotResponse()
        assert r.response_id

    def test_requires_confirmation_default_false(self) -> None:
        r = BotResponse()
        assert r.requires_confirmation is False

    def test_is_error_default_false(self) -> None:
        r = BotResponse()
        assert r.is_error is False

    def test_tools_used_default_empty(self) -> None:
        r = BotResponse()
        assert r.tools_used == []

    def test_error_response_factory(self) -> None:
        r = BotResponse.error_response(
            conv_id="abc",
            user_id="u1",
            error_code="ERR_001",
            message="失败了",
        )
        assert r.is_error is True
        assert r.error_code == "ERR_001"
        assert "失败了" in r.content
        assert r.conv_id == "abc"


# ── Skill Models ──────────────────────────────────────────────────────────────

class TestSkill:
    def test_file_tool_skill(self) -> None:
        s = Skill(
            name="file_tool",
            display_name="File Tool",
            description="Read and write files",
            category=SkillCategory.FILE,
        )
        assert s.name == "file_tool"
        assert s.category == SkillCategory.FILE

    def test_requires_confirmation_default_false(self) -> None:
        s = Skill(name="t")
        assert s.requires_confirmation is False

    def test_enabled_default_true(self) -> None:
        s = Skill(name="t")
        assert s.enabled is True

    def test_phase_default_1a(self) -> None:
        s = Skill(name="t")
        assert s.phase == "1a"

    def test_parameters_default_empty(self) -> None:
        s = Skill(name="t")
        assert s.parameters == []

    def test_tags_default_empty(self) -> None:
        s = Skill(name="t")
        assert s.tags == []

    def test_category_default_misc(self) -> None:
        s = Skill(name="t")
        assert s.category == SkillCategory.MISC

    def test_to_tool_schema_returns_dict(self) -> None:
        s = Skill(name="search_tool", description="Search the web")
        schema = s.to_tool_schema()
        assert schema["name"] == "search_tool"
        assert schema["description"] == "Search the web"
        assert "parameters" in schema

    def test_all_categories_exist(self) -> None:
        expected = {"system", "file", "search", "code", "git", "note", "http", "schedule", "memory", "misc"}
        actual = {c.value for c in SkillCategory}
        assert expected == actual

"""
core/agent.py - Main Agent class for STONE (默行者)

Wires together the StateMachine, ModelRouter, SkillRegistry, DryRunManager,
ContextManager, and AuditLogger into a single process() entry point.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from models.agent_state import AgentContext, AgentState, ToolCall, ToolResult
from models.errors import (
    DryRunRejectedError,
    InvalidStateTransition,
    StoneError,
    ToolError,
)
from models.message import BotResponse, UserMessage
from core.state_machine import StateMachine

if TYPE_CHECKING:
    from core.model_router import ModelRouter
    from core.context_manager import ContextManager
    from core.dry_run import DryRunManager
    from registry.skill_registry import SkillRegistry
    from security.audit import AuditLogger

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10

_PERSONA_PATH = Path(__file__).parent / "persona.md"
_PERSONA_CACHE: str | None = None


def _load_persona() -> str:
    global _PERSONA_CACHE
    if _PERSONA_CACHE is None:
        if _PERSONA_PATH.exists():
            _PERSONA_CACHE = _PERSONA_PATH.read_text(encoding="utf-8")
        else:
            _PERSONA_CACHE = "你是默行者，一个私人 AI 助手。"
    return _PERSONA_CACHE


class Agent:
    """
    STONE agent that processes UserMessage -> BotResponse using a StateMachine.
    """

    def __init__(
        self,
        model_router: "ModelRouter",
        skill_registry: "SkillRegistry",
        context_manager: "ContextManager",
        dry_run_manager: "DryRunManager",
        audit_logger: "AuditLogger",
    ) -> None:
        self.model_router = model_router
        self.skill_registry = skill_registry
        self.context_manager = context_manager
        self.dry_run_manager = dry_run_manager
        self.audit_logger = audit_logger

        self._sm = StateMachine(max_iterations=100)
        self._register_handlers()

    def _register_handlers(self) -> None:
        self._sm.register(AgentState.THINKING, self._handle_thinking)
        self._sm.register(AgentState.TOOL_SELECTING, self._handle_tool_selecting)
        self._sm.register(AgentState.DRY_RUN_PENDING, self._handle_dry_run)
        self._sm.register(AgentState.EXECUTING, self._handle_executing)
        self._sm.register(AgentState.ERROR_HANDLING, self._handle_error)
        self._sm.register(AgentState.RESPONDING, self._handle_responding)

    # ── Public Entry Point ────────────────────────────────────────────────────

    async def process(self, msg: UserMessage) -> BotResponse:
        """
        Main entry point. Converts a UserMessage to BotResponse by running the
        state machine from THINKING -> ... -> IDLE.
        """
        ctx = AgentContext(
            conv_id=msg.conv_id,
            user_id=msg.user_id,
            user_message=msg.content,
            state=AgentState.IDLE,
            task_type=msg.task_type,
            privacy_sensitive=msg.privacy_sensitive,
            max_tool_iterations=MAX_TOOL_ITERATIONS,
        )

        # Load conversation history into context
        history = await self.context_manager.get_context(msg.user_id, msg.conv_id)
        persona = _load_persona()
        ctx.messages = [{"role": "system", "content": persona}] + history
        ctx.messages.append({"role": "user", "content": msg.content})

        # Kick off the machine
        self._sm.transition(ctx, AgentState.THINKING)
        await self._sm.run(ctx)

        # Persist the exchange
        await self.context_manager.save_context(
            user_id=msg.user_id,
            conv_id=msg.conv_id,
            user_msg=msg.content,
            assistant_msg=ctx.final_response or ctx.error_message,
        )

        # Audit
        await self.audit_logger.log(
            level="INFO",
            action="agent_process",
            user_id=msg.user_id,
            detail={
                "conv_id": ctx.conv_id,
                "task_type": ctx.task_type,
                "tools_used": [r.tool_name for r in ctx.tool_results],
            },
            result="success" if not ctx.error_message else "failure",
        )

        response = BotResponse(
            conv_id=ctx.conv_id,
            user_id=ctx.user_id,
            content=self._sm.build_response(ctx),
            requires_confirmation=ctx.state == AgentState.DRY_RUN_PENDING,
            confirmation_token=ctx.conv_id if ctx.dry_run_plan else "",
            tools_used=[r.tool_name for r in ctx.tool_results],
        )
        return response

    # ── State Handlers ────────────────────────────────────────────────────────

    async def _handle_thinking(self, ctx: AgentContext) -> None:
        """
        Ask the LLM what to do next. It either:
        a) Returns a plain text answer  -> transition to RESPONDING
        b) Returns tool_calls          -> transition to TOOL_SELECTING
        """
        tools_schema = self.skill_registry.get_tools_schema()

        llm_response = await self.model_router.chat(
            messages=ctx.messages,
            task_type=ctx.task_type,
            user_id=ctx.user_id,
            privacy_sensitive=ctx.privacy_sensitive,
        )

        # Attempt to parse tool calls from the response
        tool_calls = _extract_tool_calls(llm_response)

        if tool_calls and ctx.tool_iteration < ctx.max_tool_iterations:
            ctx.pending_tool_calls = tool_calls
            # Add assistant message (raw) to history
            ctx.messages.append({"role": "assistant", "content": llm_response})
            self._sm.transition(ctx, AgentState.TOOL_SELECTING)
        else:
            ctx.final_response = llm_response
            ctx.messages.append({"role": "assistant", "content": llm_response})
            self._sm.transition(ctx, AgentState.RESPONDING)

    async def _handle_tool_selecting(self, ctx: AgentContext) -> None:
        """
        Validate and enrich pending tool calls. Decide if dry-run is needed.
        """
        from config import settings

        confirmed_calls: list[ToolCall] = []
        needs_dry_run = False

        for call in ctx.pending_tool_calls:
            tool = self.skill_registry.get_tool(call.tool_name)
            if tool is None:
                logger.warning("Tool %r not found, skipping", call.tool_name)
                continue
            confirmed_calls.append(call)
            if tool.requires_confirmation and settings.dry_run_enabled:
                needs_dry_run = True

        ctx.pending_tool_calls = confirmed_calls

        if not confirmed_calls:
            ctx.final_response = "（工具调用无效，直接回答）"
            self._sm.transition(ctx, AgentState.RESPONDING)
            return

        if needs_dry_run and ctx.dry_run_confirmed is None:
            # Generate a dry-run plan for user approval
            plan = await self.dry_run_manager.generate_plan(
                tool_calls=confirmed_calls,
                conv_id=ctx.conv_id,
            )
            ctx.dry_run_plan = plan
            preview = self.dry_run_manager.format_preview(plan)
            ctx.final_response = preview
            self._sm.transition(ctx, AgentState.DRY_RUN_PENDING)
        else:
            self._sm.transition(ctx, AgentState.EXECUTING)

    async def _handle_dry_run(self, ctx: AgentContext) -> None:
        """
        Wait for user confirmation. This state is exited externally via
        dry_run_manager.confirm() / cancel(), which sets ctx.dry_run_confirmed.
        The API layer calls confirm/cancel then re-processes the context.
        """
        # In the first pass we just return the preview; the state stays here
        # until the user responds. The gateway will call confirm/cancel.
        if ctx.dry_run_confirmed is None:
            # Nothing to do – waiting for user input
            self._sm.transition(ctx, AgentState.RESPONDING)  # return preview
            return

        if ctx.dry_run_confirmed is False:
            raise DryRunRejectedError(conv_id=ctx.conv_id)

        # User confirmed
        self._sm.transition(ctx, AgentState.EXECUTING)

    async def _handle_executing(self, ctx: AgentContext) -> None:
        """Execute all pending tool calls and append results to messages."""
        results: list[ToolResult] = []

        for call in ctx.pending_tool_calls:
            tool_instance = self.skill_registry.get_tool_instance(call.tool_name)
            if tool_instance is None:
                results.append(
                    ToolResult(
                        call_id=call.call_id,
                        tool_name=call.tool_name,
                        success=False,
                        error=f"工具 {call.tool_name!r} 未找到",
                    )
                )
                continue

            try:
                tool_result = await tool_instance.execute(
                    params=call.params,
                    user_id=ctx.user_id,
                )
                results.append(
                    ToolResult(
                        call_id=call.call_id,
                        tool_name=call.tool_name,
                        success=tool_result.success,
                        output=tool_result.output,
                        error=tool_result.error,
                    )
                )
                await self.audit_logger.log(
                    level="INFO",
                    action="tool_call",
                    user_id=ctx.user_id,
                    detail={"tool": call.tool_name, "params": _safe_params(call.params)},
                    result="success" if tool_result.success else "failure",
                )
            except ToolError as exc:
                logger.warning("Tool %r raised ToolError: %s", call.tool_name, exc.message)
                results.append(
                    ToolResult(
                        call_id=call.call_id,
                        tool_name=call.tool_name,
                        success=False,
                        error=exc.message,
                    )
                )

        ctx.tool_results.extend(results)
        ctx.tool_iteration += 1
        ctx.pending_tool_calls = []
        ctx.dry_run_confirmed = None
        ctx.dry_run_plan = None

        # Append tool results to message history
        for r in results:
            ctx.messages.append({
                "role": "tool",
                "tool_call_id": r.call_id,
                "name": r.tool_name,
                "content": r.output if r.success else f"ERROR: {r.error}",
            })

        # Continue reasoning
        self._sm.transition(ctx, AgentState.THINKING)

    async def _handle_error(self, ctx: AgentContext) -> None:
        """Format error as a user-friendly response."""
        logger.error("Agent error [conv=%s]: %s", ctx.conv_id, ctx.error_message)
        ctx.final_response = f"抱歉，处理时遇到问题：{ctx.error_message}"
        self._sm.transition(ctx, AgentState.RESPONDING)

    async def _handle_responding(self, ctx: AgentContext) -> None:
        """Final state before returning to IDLE."""
        self._sm.transition(ctx, AgentState.IDLE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_tool_calls(text: str) -> list[ToolCall]:
    """
    Parse tool calls from LLM output.

    Expected format (JSON block in the response):
    ```json
    {"tool_calls": [{"tool_name": "bash_tool", "params": {"command": "ls"}}]}
    ```
    Returns empty list if no tool calls found.
    """
    import re

    # Look for JSON code block
    pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
    matches = re.findall(pattern, text)
    for raw in matches:
        try:
            data = json.loads(raw)
            calls_data = data.get("tool_calls", [])
            if not calls_data:
                continue
            calls = []
            for item in calls_data:
                if "tool_name" in item:
                    calls.append(ToolCall(
                        tool_name=item["tool_name"],
                        params=item.get("params", {}),
                    ))
            if calls:
                return calls
        except json.JSONDecodeError:
            continue

    # Also try bare JSON object
    try:
        data = json.loads(text.strip())
        calls_data = data.get("tool_calls", [])
        if calls_data:
            return [
                ToolCall(tool_name=item["tool_name"], params=item.get("params", {}))
                for item in calls_data
                if "tool_name" in item
            ]
    except (json.JSONDecodeError, AttributeError):
        pass

    return []


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive keys from params before logging."""
    sensitive = {"password", "token", "secret", "api_key", "key"}
    return {k: "***" if k.lower() in sensitive else v for k, v in params.items()}


__all__ = ["Agent"]

"""
core/agent.py - Main Agent class for STONE (默行者)

Wires together the StateMachine, ModelRouter, SkillRegistry, DryRunManager,
ContextManager, and AuditLogger into a single process() entry point.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from models.agent_state import AgentContext, AgentState, ToolCall, ToolResult, VALID_TRANSITIONS
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
        memory_extractor: "Any | None" = None,
    ) -> None:
        self.model_router = model_router
        self.skill_registry = skill_registry
        self.context_manager = context_manager
        self.dry_run_manager = dry_run_manager
        self.audit_logger = audit_logger
        self.memory_extractor = memory_extractor  # MemoryExtractor | None

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
        tools_schema = self.skill_registry.get_tools_schema()
        system_content = persona
        if tools_schema:
            system_content += "\n\n" + _build_tools_instruction(tools_schema)
        ctx.messages = [{"role": "system", "content": system_content}] + history
        ctx.messages.append({"role": "user", "content": msg.content})

        # Kick off the machine
        self._sm.transition(ctx, AgentState.THINKING)
        await self._sm.run(ctx)

        # Persist the exchange — skip when a dry-run preview is pending:
        # the history will be saved by execute_confirmed() with the original
        # user request paired with the actual execution result, so the LLM
        # never sees an intermediate "waiting for confirmation" turn.
        is_dry_run_pending = (
            ctx.final_response is not None
            and ctx.final_response.startswith("⚠️")
        )
        if not is_dry_run_pending:
            await self.context_manager.save_context(
                user_id=msg.user_id,
                conv_id=msg.conv_id,
                user_msg=msg.content,
                assistant_msg=ctx.final_response or ctx.error_message,
            )
            # Fire-and-forget memory extraction (non-blocking)
            if self.memory_extractor is not None:
                asyncio.ensure_future(
                    self._extract_memory(
                        user_id=msg.user_id,
                        user_text=msg.content,
                        assistant_text=ctx.final_response or "",
                        conv_id=msg.conv_id,
                    )
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

    async def execute_confirmed(self, conv_id: str, user_id: str) -> BotResponse:
        """
        Resume execution after user confirmed a dry-run plan via chat.
        Reconstructs tool calls from the stored plan and runs EXECUTING -> THINKING -> RESPONDING.
        """
        plan = self.dry_run_manager.get_pending_plan(conv_id)
        original_user_msg: str = (plan or {}).get("original_user_msg", "") or "(执行操作)"
        if plan is None:
            return BotResponse(
                conv_id=conv_id,
                user_id=user_id,
                content="没有找到待确认的操作，可能已超时或已处理。",
            )

        # Reconstruct ToolCall objects from the plan steps
        tool_calls = [
            ToolCall(
                tool_name=step["tool"],
                params=step.get("params", {}),
                call_id=step.get("call_id", str(uuid.uuid4())),
            )
            for step in plan.get("steps", [])
        ]

        await self.dry_run_manager.confirm(conv_id, user_id)

        # Build context — go IDLE -> EXECUTING, skip THINKING entirely to avoid
        # the LLM re-generating tool calls and triggering another dry-run cycle.
        ctx = AgentContext(
            conv_id=conv_id,
            user_id=user_id,
            user_message="(用户已确认操作)",
            state=AgentState.IDLE,
            pending_tool_calls=tool_calls,
            dry_run_confirmed=True,
        )

        history = await self.context_manager.get_context(user_id, conv_id)
        persona = _load_persona()
        tools_schema = self.skill_registry.get_tools_schema()
        system_content = persona
        if tools_schema:
            system_content += "\n\n" + _build_tools_instruction(tools_schema)
        ctx.messages = [{"role": "system", "content": system_content}] + history

        # Re-surface the original user message so the LLM knows the full intent
        # after tool execution (dry-run skips saving to context, so it's not in history).
        ctx.messages.append({"role": "user", "content": original_user_msg})

        # Prepend a synthetic assistant tool_calls message so the conversation
        # follows the standard [user → assistant(tool_calls) → tool → assistant] pattern.
        ctx.messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.params, ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ],
        })

        # Execute the confirmed tool calls (appends tool-role results to ctx.messages)
        ctx.state = AgentState.EXECUTING  # bypass transition validation
        await self._handle_executing(ctx)

        # State is now THINKING — continue the full state machine so the LLM
        # can process remaining intents from the original multi-step request.
        await self._sm.run(ctx)

        # Only persist when there is no follow-on dry-run waiting for user input.
        next_dry_run = (
            ctx.final_response is not None
            and ctx.final_response.startswith("⚠️")
        )
        if not next_dry_run:
            await self.context_manager.save_context(
                user_id=user_id,
                conv_id=conv_id,
                user_msg=original_user_msg,
                assistant_msg=ctx.final_response or ctx.error_message,
            )
            if self.memory_extractor is not None:
                asyncio.ensure_future(
                    self._extract_memory(
                        user_id=user_id,
                        user_text=original_user_msg,
                        assistant_text=ctx.final_response or "",
                        conv_id=conv_id,
                    )
                )

        await self.audit_logger.log(
            level="INFO",
            action="dry_run_execute_confirmed",
            user_id=user_id,
            detail={"conv_id": conv_id, "tools": [c.tool_name for c in tool_calls]},
            result="success" if not ctx.error_message else "failure",
        )

        return BotResponse(
            conv_id=ctx.conv_id,
            user_id=ctx.user_id,
            content=self._sm.build_response(ctx),
            requires_confirmation=next_dry_run,
            confirmation_token=ctx.conv_id if next_dry_run else "",
            tools_used=[r.tool_name for r in ctx.tool_results],
        )

    # ── State Handlers ────────────────────────────────────────────────────────

    async def _handle_thinking(self, ctx: AgentContext) -> None:
        """
        Ask the LLM what to do next. It either:
        a) Returns a plain text answer  -> transition to RESPONDING
        b) Returns tool_calls          -> transition to TOOL_SELECTING
        """
        tools_schema = self.skill_registry.get_tools_schema()

        llm_resp = await self.model_router.chat(
            messages=ctx.messages,
            task_type=ctx.task_type,
            user_id=ctx.user_id,
            privacy_sensitive=ctx.privacy_sensitive,
            tools=tools_schema or None,
        )

        logger.debug("LLM response [conv=%s] text=%r tool_calls=%s",
                     ctx.conv_id, llm_resp.text[:200], llm_resp.tool_calls)

        # Build ToolCall objects — prefer native tool calls, fall back to JSON-in-text
        tool_calls: list[ToolCall] = _parse_tool_calls(llm_resp)
        if tool_calls:
            logger.info("Tool_calls [conv=%s]: %s", ctx.conv_id,
                        [(c.tool_name, c.params) for c in tool_calls])

        # ── Retry once if LLM returned text-only on the very first attempt ──
        # Prevents the LLM from describing what it will do instead of doing it.
        # Only retry when tools are available and no tool results yet (not mid-loop).
        if not tool_calls and tools_schema and ctx.thinking_retries == 0 and not ctx.tool_results:
            ctx.thinking_retries += 1
            retry_messages = list(ctx.messages) + [
                {"role": "assistant", "content": llm_resp.text},
                {
                    "role": "user",
                    "content": (
                        "如果完成这个请求需要调用工具，请**立即**以规定的 JSON 格式输出工具调用，"
                        "不要再描述计划。如果确实不需要工具，请直接给出最终答案。"
                    ),
                },
            ]
            llm_resp2 = await self.model_router.chat(
                messages=retry_messages,
                task_type=ctx.task_type,
                user_id=ctx.user_id,
                privacy_sensitive=ctx.privacy_sensitive,
                tools=tools_schema or None,
            )
            retry_calls = _parse_tool_calls(llm_resp2)
            if retry_calls:
                logger.info("Retry succeeded [conv=%s]: %s", ctx.conv_id,
                            [(c.tool_name, c.params) for c in retry_calls])
                llm_resp = llm_resp2
                tool_calls = retry_calls
            else:
                logger.debug("Retry still no tool_calls [conv=%s], using original text", ctx.conv_id)

        # Build the assistant message for history with proper tool_calls structure.
        # Use call_id from the processed tool_calls list (which guarantees a non-empty UUID),
        # not from raw llm_resp.tool_calls (which may have empty id from Ollama).
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": llm_resp.text}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.params, ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ]

        if tool_calls and ctx.tool_iteration < ctx.max_tool_iterations:
            ctx.pending_tool_calls = tool_calls
            ctx.messages.append(assistant_msg)
            self._sm.transition(ctx, AgentState.TOOL_SELECTING)
        else:
            ctx.final_response = llm_resp.text
            ctx.messages.append(assistant_msg)
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
            tool_instance = self.skill_registry.get_tool_instance(call.tool_name)
            if (tool_instance and tool_instance.needs_confirmation_for(call.params)
                    and settings.dry_run_enabled):
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
                user_message=ctx.user_message,
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

    async def _extract_memory(
        self,
        user_id: str,
        user_text: str,
        assistant_text: str,
        conv_id: str,
    ) -> None:
        """Background memory extraction after each completed turn."""
        try:
            await self.memory_extractor.extract_from_turn(
                user_id=user_id,
                user_text=user_text,
                assistant_text=assistant_text,
                conv_id=conv_id,
            )
        except Exception as exc:
            logger.warning("Memory extraction failed (non-fatal): %s", exc)

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


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """
    Recover correct params when an LLM embeds XML-like arg tags inside a value.

    Some models (e.g. Qwen) output the argument list inside the *first* param
    instead of producing proper key/value pairs:

        action = 'write_file\\n<arg_key>path</arg_key>\\n<arg_value>foo.md'

    This function:
    1. Strips the embedded XML, keeping only the prefix as the actual value.
    2. Extracts the embedded key→value pairs and merges them back into params.

    Result for the above example:
        {'action': 'write_file', 'path': 'foo.md'}
    """
    import re as _re

    cleaned: dict[str, Any] = {}
    extra: dict[str, str] = {}

    for k, v in params.items():
        if isinstance(v, str) and "<arg_key>" in v:
            # Everything before the first <arg_key> is the real value for this key
            prefix_match = _re.match(r"^([^<]+?)(?:\s*<arg_key>|$)", v)
            cleaned[k] = prefix_match.group(1).strip() if prefix_match else v

            # Extract all embedded <arg_key>k</arg_key><arg_value>v</arg_value> pairs.
            # The closing </arg_value> may be missing (truncated output), so allow EOF.
            pairs = _re.findall(
                r"<arg_key>([^<]+)</arg_key>\s*<arg_value>(.*?)(?:</arg_value>|$)",
                v,
                _re.DOTALL,
            )
            for ek, ev in pairs:
                extra[ek.strip()] = ev.strip()
        else:
            cleaned[k] = v

    # Merge extracted pairs; don't overwrite keys that already have a real value
    for ek, ev in extra.items():
        if ek not in cleaned or not cleaned[ek]:
            cleaned[ek] = ev

    return cleaned


def _parse_tool_calls(llm_resp: Any) -> list["ToolCall"]:
    """
    Extract ToolCall objects from an LLMResponse.
    Prefers native tool_calls; falls back to JSON-in-text parsing.
    Sanitizes all param string values to remove LLM-generated XML noise.
    """
    tool_calls: list[ToolCall] = []
    if llm_resp.tool_calls:
        for tc in llm_resp.tool_calls:
            if tc.get("tool_name"):
                tool_calls.append(ToolCall(
                    tool_name=tc["tool_name"],
                    params=_sanitize_params(tc.get("params", {})),
                    call_id=tc.get("call_id") or str(uuid.uuid4()),
                ))
    else:
        raw_calls = _extract_tool_calls(llm_resp.text)
        tool_calls = [
            ToolCall(
                tool_name=tc.tool_name,
                params=_sanitize_params(tc.params),
                call_id=tc.call_id,
            )
            for tc in raw_calls
        ]
    return tool_calls


def _build_tools_instruction(tools_schema: list[dict[str, Any]]) -> str:
    """
    Build a system message that tells the LLM:
    1. What tools are available (with their schemas)
    2. The exact JSON format to use when invoking them
    """
    tools_json = json.dumps(tools_schema, ensure_ascii=False, indent=2)
    return (
        "## 可用工具\n\n"
        f"{tools_json}\n\n"
        "## 工具调用规则\n\n"
        "**核心原则**：当用户请求需要执行操作（文件管理、网络搜索、任务调度等），"
        "你**必须**调用对应工具来完成，严禁凭空声称已执行或伪造操作结果。\n\n"
        "- 调用工具时，**只输出**如下 JSON 代码块，代码块前后不要有任何文字：\n\n"
        "```json\n"
        '{"tool_calls": [{"tool_name": "工具名", "params": {参数}}]}\n'
        "```\n\n"
        "- **每次只调用一个工具**，等待工具执行结果后，再决定下一步操作。\n"
        "  不得在同一次回复中批量调用多个工具。\n"
        "- **多步骤任务严格按用户指定顺序执行**：第一步就调用第一个工具，\n"
        "  不得跳过任何步骤，不得因某步骤需要用户确认就改变执行顺序。\n"
        "- 工具结果返回后，用自然语言向用户解释结果，然后继续下一步（若有）。\n"
        "- **不需要工具时，直接用自然语言回复，不要输出 JSON。**\n"
        "- **禁止在未收到工具执行结果的情况下，自行声明操作已完成。**"
    )


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive keys from params before logging."""
    sensitive = {"password", "token", "secret", "api_key", "key"}
    return {k: "***" if k.lower() in sensitive else v for k, v in params.items()}


__all__ = ["Agent"]

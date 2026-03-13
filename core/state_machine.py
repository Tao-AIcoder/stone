"""
core/state_machine.py - Agent state machine for STONE (默行者)

Drives the agent through its states via registered handlers, validates
transitions against VALID_TRANSITIONS, and enforces iteration limits.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from models.agent_state import VALID_TRANSITIONS, AgentContext, AgentState
from models.errors import InvalidStateTransition, StoneError

logger = logging.getLogger(__name__)

# Type alias for state handler coroutines
StateHandler = Callable[[AgentContext], Awaitable[None]]


class StateMachine:
    """
    Lightweight async state machine.

    Usage::

        sm = StateMachine()
        sm.register(AgentState.THINKING, my_thinking_handler)
        ...
        await sm.run(ctx)
    """

    def __init__(self, max_iterations: int = 50) -> None:
        self._handlers: dict[AgentState, StateHandler] = {}
        self.max_iterations = max_iterations

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, state: AgentState, handler: StateHandler) -> None:
        """Associate a coroutine handler with a state."""
        if state in self._handlers:
            logger.warning("Overwriting handler for state %s", state)
        self._handlers[state] = handler
        logger.debug("Registered handler for state %s", state)

    # ── Transition ───────────────────────────────────────────────────────────

    def transition(self, ctx: AgentContext, new_state: AgentState) -> None:
        """
        Validate and apply a state transition.

        Raises:
            InvalidStateTransition: if the transition is not in VALID_TRANSITIONS.
        """
        current = ctx.state
        allowed = VALID_TRANSITIONS.get(current, set())

        if new_state not in allowed:
            raise InvalidStateTransition(
                from_state=current.value,
                to_state=new_state.value,
            )

        logger.debug(
            "State transition [conv=%s]: %s -> %s",
            ctx.conv_id,
            current.value,
            new_state.value,
        )
        ctx.state = new_state
        ctx.mark_updated()

    # ── Main Loop ────────────────────────────────────────────────────────────

    async def run(self, ctx: AgentContext) -> AgentContext:
        """
        Execute the state machine starting from ctx.state until IDLE or
        max_iterations is reached.

        Returns the final context (state == IDLE or state == RESPONDING).
        """
        iterations = 0

        while ctx.state not in (AgentState.IDLE,) and iterations < self.max_iterations:
            iterations += 1
            current_state = ctx.state

            handler = self._handlers.get(current_state)
            if handler is None:
                logger.error("No handler registered for state %s", current_state)
                ctx.error_message = f"内部错误：状态 {current_state.value} 没有处理器"
                self.transition(ctx, AgentState.ERROR_HANDLING)
                # If error handler also missing, break to avoid infinite loop
                if self._handlers.get(AgentState.ERROR_HANDLING) is None:
                    break
                continue

            try:
                await handler(ctx)
            except InvalidStateTransition:
                raise
            except StoneError as exc:
                logger.warning(
                    "StoneError in state %s [conv=%s]: %s",
                    current_state,
                    ctx.conv_id,
                    exc.message,
                )
                ctx.error_message = exc.message
                if ctx.state != AgentState.ERROR_HANDLING:
                    try:
                        self.transition(ctx, AgentState.ERROR_HANDLING)
                    except InvalidStateTransition:
                        # Cannot transition to error from current state; force RESPONDING
                        ctx.state = AgentState.RESPONDING
            except Exception as exc:
                logger.exception(
                    "Unexpected error in state %s [conv=%s]",
                    current_state,
                    ctx.conv_id,
                )
                ctx.error_message = f"内部错误：{exc}"
                if ctx.state != AgentState.ERROR_HANDLING:
                    try:
                        self.transition(ctx, AgentState.ERROR_HANDLING)
                    except InvalidStateTransition:
                        ctx.state = AgentState.RESPONDING

            # Safety: if state did not change, something is wrong
            if ctx.state == current_state:
                logger.error(
                    "State did not change after handling %s (iteration %d); aborting",
                    current_state,
                    iterations,
                )
                ctx.error_message = "状态机死锁，强制终止"
                ctx.state = AgentState.RESPONDING
                break

        if iterations >= self.max_iterations:
            logger.warning(
                "State machine reached max_iterations=%d [conv=%s]",
                self.max_iterations,
                ctx.conv_id,
            )
            ctx.error_message = "操作超出最大迭代次数，已强制终止"
            ctx.state = AgentState.IDLE

        return ctx

    # ── Helper ────────────────────────────────────────────────────────────────

    @staticmethod
    def build_response(ctx: AgentContext) -> str:
        """
        Return the best available response text from the context.
        Prefers final_response; falls back to error_message.
        """
        if ctx.final_response:
            return ctx.final_response
        if ctx.error_message:
            return f"⚠️ {ctx.error_message}"
        return "（无回复）"


__all__ = ["StateMachine", "StateHandler"]

"""
tests/test_state_machine.py - Unit tests for the STONE state machine.
"""

from __future__ import annotations

import asyncio
import sys
import os

import pytest

# Ensure the stone package root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.agent_state import AgentContext, AgentState, VALID_TRANSITIONS
from models.errors import InvalidStateTransition
from core.state_machine import StateMachine


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_context(user_msg: str = "hello") -> AgentContext:
    return AgentContext(
        user_id="test_user",
        user_message=user_msg,
        state=AgentState.IDLE,
    )


# ── Transition Tests ──────────────────────────────────────────────────────────

class TestTransitions:
    def test_idle_to_thinking_valid(self) -> None:
        sm = StateMachine()
        ctx = make_context()
        sm.transition(ctx, AgentState.THINKING)
        assert ctx.state == AgentState.THINKING

    def test_idle_to_executing_invalid(self) -> None:
        sm = StateMachine()
        ctx = make_context()
        with pytest.raises(InvalidStateTransition) as exc_info:
            sm.transition(ctx, AgentState.EXECUTING)
        assert exc_info.value.from_state == "IDLE"
        assert exc_info.value.to_state == "EXECUTING"

    def test_thinking_to_responding_valid(self) -> None:
        sm = StateMachine()
        ctx = make_context()
        sm.transition(ctx, AgentState.THINKING)
        sm.transition(ctx, AgentState.RESPONDING)
        assert ctx.state == AgentState.RESPONDING

    def test_thinking_to_tool_selecting_valid(self) -> None:
        sm = StateMachine()
        ctx = make_context()
        sm.transition(ctx, AgentState.THINKING)
        sm.transition(ctx, AgentState.TOOL_SELECTING)
        assert ctx.state == AgentState.TOOL_SELECTING

    def test_responding_to_idle_valid(self) -> None:
        sm = StateMachine()
        ctx = make_context()
        sm.transition(ctx, AgentState.THINKING)
        sm.transition(ctx, AgentState.RESPONDING)
        sm.transition(ctx, AgentState.IDLE)
        assert ctx.state == AgentState.IDLE

    def test_all_valid_transitions_defined(self) -> None:
        """Verify VALID_TRANSITIONS covers all states."""
        for state in AgentState:
            assert state in VALID_TRANSITIONS, f"State {state} missing from VALID_TRANSITIONS"

    def test_invalid_transition_carries_state_names(self) -> None:
        sm = StateMachine()
        ctx = make_context()
        ctx.state = AgentState.RESPONDING
        with pytest.raises(InvalidStateTransition) as exc_info:
            sm.transition(ctx, AgentState.THINKING)
        e = exc_info.value
        assert e.from_state == AgentState.RESPONDING.value
        assert e.to_state == AgentState.THINKING.value
        assert "RESPONDING" in str(e)
        assert "THINKING" in str(e)


# ── Run Loop Tests ────────────────────────────────────────────────────────────

class TestStateMachineRun:
    @pytest.mark.asyncio
    async def test_simple_run_idle_to_idle(self) -> None:
        """A machine that immediately transitions to RESPONDING should end in IDLE."""
        sm = StateMachine()

        async def thinking_handler(ctx: AgentContext) -> None:
            ctx.final_response = "computed answer"
            sm.transition(ctx, AgentState.RESPONDING)

        async def responding_handler(ctx: AgentContext) -> None:
            sm.transition(ctx, AgentState.IDLE)

        sm.register(AgentState.THINKING, thinking_handler)
        sm.register(AgentState.RESPONDING, responding_handler)

        ctx = make_context()
        sm.transition(ctx, AgentState.THINKING)
        result = await sm.run(ctx)

        assert result.state == AgentState.IDLE
        assert result.final_response == "computed answer"

    @pytest.mark.asyncio
    async def test_max_iterations_stops_infinite_loop(self) -> None:
        """State machine must stop when max_iterations is exceeded."""
        sm = StateMachine(max_iterations=5)

        call_count = 0

        async def looping_handler(ctx: AgentContext) -> None:
            nonlocal call_count
            call_count += 1
            # Never transitions out - simulates a buggy handler
            # But we need to change state to avoid "state did not change" abort
            # Switch between THINKING and TOOL_SELECTING
            if ctx.state == AgentState.THINKING:
                sm.transition(ctx, AgentState.TOOL_SELECTING)
            else:
                sm.transition(ctx, AgentState.THINKING)

        sm.register(AgentState.THINKING, looping_handler)
        sm.register(AgentState.TOOL_SELECTING, looping_handler)

        ctx = make_context()
        sm.transition(ctx, AgentState.THINKING)
        result = await sm.run(ctx)

        # Should have stopped; call_count <= max_iterations
        assert call_count <= sm.max_iterations
        assert result.error_message != ""

    @pytest.mark.asyncio
    async def test_error_handling_state(self) -> None:
        """An exception in a handler should route to ERROR_HANDLING."""
        sm = StateMachine()

        async def bad_thinking(ctx: AgentContext) -> None:
            raise ValueError("simulated failure")

        async def error_handler(ctx: AgentContext) -> None:
            ctx.final_response = f"handled: {ctx.error_message}"
            sm.transition(ctx, AgentState.RESPONDING)

        async def responding_handler(ctx: AgentContext) -> None:
            sm.transition(ctx, AgentState.IDLE)

        sm.register(AgentState.THINKING, bad_thinking)
        sm.register(AgentState.ERROR_HANDLING, error_handler)
        sm.register(AgentState.RESPONDING, responding_handler)

        ctx = make_context()
        sm.transition(ctx, AgentState.THINKING)
        result = await sm.run(ctx)

        assert result.state == AgentState.IDLE
        assert "handled:" in result.final_response

    @pytest.mark.asyncio
    async def test_full_run_idle_thinking_responding_idle(self) -> None:
        """Full happy-path run from THINKING to IDLE."""
        sm = StateMachine()
        events: list[str] = []

        async def thinking_h(ctx: AgentContext) -> None:
            events.append("thinking")
            ctx.final_response = "42"
            sm.transition(ctx, AgentState.RESPONDING)

        async def responding_h(ctx: AgentContext) -> None:
            events.append("responding")
            sm.transition(ctx, AgentState.IDLE)

        sm.register(AgentState.THINKING, thinking_h)
        sm.register(AgentState.RESPONDING, responding_h)

        ctx = make_context("what is the answer?")
        sm.transition(ctx, AgentState.THINKING)
        result = await sm.run(ctx)

        assert events == ["thinking", "responding"]
        assert result.state == AgentState.IDLE
        assert result.final_response == "42"

    def test_build_response_uses_final_response(self) -> None:
        ctx = make_context()
        ctx.final_response = "hello world"
        ctx.error_message = "some error"
        assert StateMachine.build_response(ctx) == "hello world"

    def test_build_response_falls_back_to_error(self) -> None:
        ctx = make_context()
        ctx.final_response = ""
        ctx.error_message = "boom"
        result = StateMachine.build_response(ctx)
        assert "boom" in result

    def test_build_response_empty_context(self) -> None:
        ctx = make_context()
        result = StateMachine.build_response(ctx)
        assert result  # Should return something, not empty

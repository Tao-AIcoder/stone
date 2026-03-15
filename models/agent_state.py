"""
models/agent_state.py - Agent state machine definitions for STONE (默行者)

Defines the AgentState enum, the valid transition table, and the
AgentContext Pydantic model that flows through the state machine.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentState(str, Enum):
    """All possible states of the STONE agent."""

    IDLE = "IDLE"
    THINKING = "THINKING"
    TOOL_SELECTING = "TOOL_SELECTING"
    DRY_RUN_PENDING = "DRY_RUN_PENDING"
    EXECUTING = "EXECUTING"
    ERROR_HANDLING = "ERROR_HANDLING"
    RESPONDING = "RESPONDING"


# Valid state transitions.
# Key = current state, Value = set of states that may be entered from it.
VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {AgentState.THINKING},
    AgentState.THINKING: {
        AgentState.TOOL_SELECTING,
        AgentState.RESPONDING,
        AgentState.ERROR_HANDLING,
    },
    AgentState.TOOL_SELECTING: {
        AgentState.DRY_RUN_PENDING,
        AgentState.EXECUTING,
        AgentState.RESPONDING,
        AgentState.ERROR_HANDLING,
    },
    AgentState.DRY_RUN_PENDING: {
        AgentState.EXECUTING,
        AgentState.RESPONDING,   # user cancelled
        AgentState.ERROR_HANDLING,
    },
    AgentState.EXECUTING: {
        AgentState.THINKING,     # tool result → continue reasoning
        AgentState.RESPONDING,
        AgentState.ERROR_HANDLING,
    },
    AgentState.ERROR_HANDLING: {
        AgentState.RESPONDING,
        AgentState.IDLE,
    },
    AgentState.RESPONDING: {
        AgentState.IDLE,
    },
}


class ToolCall(BaseModel):
    """A single tool invocation request from the model."""

    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ToolResult(BaseModel):
    """Result of executing a tool call."""

    call_id: str
    tool_name: str
    success: bool
    output: str = ""
    error: str = ""


class AgentContext(BaseModel):
    """
    Mutable context that flows through the agent state machine for a single
    request/response cycle.
    """

    # Identity
    conv_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "default_user"

    # State
    state: AgentState = AgentState.IDLE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Input
    user_message: str = ""

    # Reasoning
    messages: list[dict[str, Any]] = Field(default_factory=list)
    """Full message history sent to the LLM (system + user + assistant turns)."""

    # Tool use
    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    tool_iteration: int = 0
    max_tool_iterations: int = 10
    thinking_retries: int = 0       # counts LLM retries within _handle_thinking

    # Dry-run
    dry_run_plan: dict[str, Any] | None = None
    dry_run_confirmed: bool | None = None  # None = awaiting; True/False = decided

    # Output
    final_response: str = ""
    error_message: str = ""

    # Metadata
    task_type: str = "chat"          # chat | code | analysis | search
    privacy_sensitive: bool = False

    model_config = {"arbitrary_types_allowed": True}

    def mark_updated(self) -> None:
        self.updated_at = datetime.utcnow()


__all__ = [
    "AgentState",
    "VALID_TRANSITIONS",
    "ToolCall",
    "ToolResult",
    "AgentContext",
]

"""
models/conversation.py - Conversation and Message models for STONE (默行者)

These models are used both in-memory and for SQLite persistence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Role of the participant in a conversation turn."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Message(BaseModel):
    """A single turn in a conversation, as stored in the database."""

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conv_id: str = ""
    user_id: str = "default_user"

    role: MessageRole
    content: str
    tool_name: str = ""          # Populated when role == TOOL
    tool_call_id: str = ""       # Links tool result to tool call

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    token_count: int = 0         # Estimated tokens for context management

    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def to_llm_dict(self) -> dict[str, Any]:
        """Convert to the dict format expected by LLM APIs."""
        d: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.role == MessageRole.TOOL:
            d["tool_call_id"] = self.tool_call_id
            d["name"] = self.tool_name
        return d


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class Conversation(BaseModel):
    """Represents an ongoing or historical conversation."""

    conv_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "default_user"
    title: str = ""

    status: ConversationStatus = ConversationStatus.ACTIVE

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    message_count: int = 0
    summary: str = ""            # Compressed context summary for long conversations

    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def mark_updated(self) -> None:
        self.updated_at = datetime.utcnow()
        self.message_count += 1


__all__ = [
    "MessageRole",
    "Message",
    "ConversationStatus",
    "Conversation",
]

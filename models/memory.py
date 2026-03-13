"""
models/memory.py - Long-term memory model for STONE (默行者)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    """Semantic category for a memory fragment."""

    PREFERENCE = "preference"    # User preferences and habits
    FACT = "fact"                # Factual information about the user or world
    DECISION = "decision"        # Past decisions and rationale
    NOTE = "note"                # General notes / reminders
    SKILL = "skill"              # Learned behaviors or custom instructions
    CONTEXT = "context"          # Contextual background


class Memory(BaseModel):
    """A single long-term memory fragment stored for a user."""

    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "default_user"

    category: MemoryCategory = MemoryCategory.NOTE
    content: str                 # The actual memory text
    source: str = ""             # Where this memory came from (conv_id, etc.)

    # Confidence score 0.0–1.0; lower values may be overwritten more readily
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Tags for filtering / searching
    tags: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    accessed_at: datetime = Field(default_factory=datetime.utcnow)

    # How many times this memory has been accessed
    access_count: int = 0

    # Whether this memory is still considered relevant
    active: bool = True

    model_config = {"arbitrary_types_allowed": True}

    def touch(self) -> None:
        """Update access timestamp and increment counter."""
        self.accessed_at = datetime.utcnow()
        self.access_count += 1

    def update_content(self, new_content: str, confidence: float = 1.0) -> None:
        self.content = new_content
        self.confidence = confidence
        self.updated_at = datetime.utcnow()


__all__ = [
    "MemoryCategory",
    "Memory",
]

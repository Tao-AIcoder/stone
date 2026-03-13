"""
modules/memory/base.py - Abstract short-term memory interface for STONE.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ShortTermMemory(ABC):
    """
    Abstract interface for short-term (session) memory stores.
    Implementations must be async-safe.
    """

    @abstractmethod
    async def get_context(
        self, user_id: str, conv_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Retrieve the message list for a conversation.
        Returns None if the conversation has no stored context.
        """
        ...

    @abstractmethod
    async def save_context(
        self,
        user_id: str,
        conv_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Persist the entire message list for a conversation."""
        ...

    @abstractmethod
    async def get_summary(self, user_id: str, conv_id: str) -> str | None:
        """
        Retrieve the compressed summary for a conversation.
        Returns None if no summary exists yet.
        """
        ...

    @abstractmethod
    async def save_summary(
        self, user_id: str, conv_id: str, summary: str
    ) -> None:
        """Store a compressed conversation summary."""
        ...

    @abstractmethod
    async def delete_context(self, user_id: str, conv_id: str) -> None:
        """Remove all stored context for a conversation."""
        ...

    @abstractmethod
    async def clear_user(self, user_id: str) -> int:
        """Delete all conversations for a user. Returns number of deleted entries."""
        ...


__all__ = ["ShortTermMemory"]

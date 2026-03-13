"""
modules/interfaces/memory.py - Short-term and long-term memory interfaces.

Short-term (session) memory:
  inmemory → modules.memory.inmemory_store.InMemoryStore  (Phase 1, default)
  redis    → modules.memory.redis_store.RedisStore         (Phase 2)

Long-term (persistent) memory:
  sqlite   → modules.memory.sqlite_store.SQLiteStore       (Phase 1, default)
  postgres → modules.memory.postgres_store.PostgresStore   (future)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ── Short-Term Memory ─────────────────────────────────────────────────────────

class ShortTermMemoryInterface(ABC):
    """
    Contract for session-scoped (short-term) memory stores.

    Stores conversation message lists and compressed summaries.
    Keyed by (user_id, conv_id).
    """

    @abstractmethod
    async def get_context(
        self, user_id: str, conv_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Retrieve stored messages for a conversation.
        Returns None if no context exists yet.
        """
        ...

    @abstractmethod
    async def save_context(
        self,
        user_id: str,
        conv_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Overwrite the stored message list for a conversation."""
        ...

    @abstractmethod
    async def get_summary(self, user_id: str, conv_id: str) -> str | None:
        """Return the compressed summary, or None if not yet generated."""
        ...

    @abstractmethod
    async def save_summary(
        self, user_id: str, conv_id: str, summary: str
    ) -> None:
        """Persist a compressed conversation summary."""
        ...

    @abstractmethod
    async def delete_context(self, user_id: str, conv_id: str) -> None:
        """Remove all stored context for a specific conversation."""
        ...

    @abstractmethod
    async def clear_user(self, user_id: str) -> int:
        """Delete all conversations for a user. Returns count deleted."""
        ...


# ── Long-Term Memory ──────────────────────────────────────────────────────────

class LongTermMemoryInterface(ABC):
    """
    Contract for persistent (long-term) storage.

    Covers conversations, messages, long-term memories, audit logs,
    security logs, and scheduled tasks.
    """

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def initialize(self) -> None:
        """Create tables / schemas if they don't exist."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Flush buffers and close connections."""
        ...

    # ── Conversations ─────────────────────────────────────────────────────────

    @abstractmethod
    async def create_conversation(
        self, conv_id: str, user_id: str
    ) -> None: ...

    @abstractmethod
    async def get_conversation(self, conv_id: str) -> Any | None: ...

    @abstractmethod
    async def update_conversation_summary(
        self, conv_id: str, summary: str
    ) -> None: ...

    # ── Messages ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def save_message(
        self,
        message_id: str,
        conv_id: str,
        user_id: str,
        role: str,
        content: str,
        *,
        model_used: str = "",
        tools_used: list[str] | None = None,
        token_usage: dict[str, int] | None = None,
    ) -> None: ...

    @abstractmethod
    async def get_conversation_messages(
        self, conv_id: str, limit: int = 50, offset: int = 0
    ) -> list[Any]: ...

    # ── Long-term memories ────────────────────────────────────────────────────

    @abstractmethod
    async def save_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        *,
        source: str = "",
        confidence: float = 1.0,
        tags: list[str] | None = None,
    ) -> str: ...  # returns memory_id

    @abstractmethod
    async def get_memories(
        self,
        user_id: str,
        category: Any | None = None,
        limit: int = 50,
    ) -> list[Any]: ...

    # ── Audit / Security logs ─────────────────────────────────────────────────

    @abstractmethod
    async def save_audit_log(
        self,
        level: str,
        action: str,
        user_id: str,
        detail: dict[str, Any],
        result: str,
    ) -> None: ...

    @abstractmethod
    async def get_audit_logs(
        self,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Any]: ...

    @abstractmethod
    async def save_security_log(
        self,
        event_type: str,
        user_id: str,
        detail: str,
        source_ip: str = "",
    ) -> None: ...

    # ── Scheduled tasks ───────────────────────────────────────────────────────

    @abstractmethod
    async def save_task(self, task: Any) -> None: ...

    @abstractmethod
    async def get_tasks(self, user_id: str) -> list[Any]: ...

    @abstractmethod
    async def delete_task(self, task_id: str) -> None: ...


__all__ = ["ShortTermMemoryInterface", "LongTermMemoryInterface"]

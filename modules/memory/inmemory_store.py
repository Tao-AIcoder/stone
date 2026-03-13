"""
modules/memory/inmemory_store.py - In-memory short-term context store for STONE.

Thread-safe via asyncio.Lock. Caps total stored conversations at 1000
(LRU eviction).
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any

from modules.memory.base import ShortTermMemory

logger = logging.getLogger(__name__)

MAX_CONVERSATIONS = 1000


class InMemoryStore(ShortTermMemory):
    """
    Dictionary-based short-term memory store keyed by "user_id:conv_id".
    Maintains a separate summary dict for compressed context.
    Uses LRU eviction when MAX_CONVERSATIONS is exceeded.
    """

    def __init__(self) -> None:
        # OrderedDict for LRU: most recently used at the end
        self._contexts: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._summaries: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(user_id: str, conv_id: str) -> str:
        return f"{user_id}:{conv_id}"

    # ── ShortTermMemory interface ─────────────────────────────────────────────

    async def get_context(
        self, user_id: str, conv_id: str
    ) -> list[dict[str, Any]] | None:
        key = self._key(user_id, conv_id)
        async with self._lock:
            if key not in self._contexts:
                return None
            # Move to end (most recently used)
            self._contexts.move_to_end(key)
            return list(self._contexts[key])

    async def save_context(
        self,
        user_id: str,
        conv_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        key = self._key(user_id, conv_id)
        async with self._lock:
            self._contexts[key] = list(messages)
            self._contexts.move_to_end(key)
            await self._evict_if_needed()

    async def get_summary(self, user_id: str, conv_id: str) -> str | None:
        key = self._key(user_id, conv_id)
        async with self._lock:
            return self._summaries.get(key)

    async def save_summary(
        self, user_id: str, conv_id: str, summary: str
    ) -> None:
        key = self._key(user_id, conv_id)
        async with self._lock:
            self._summaries[key] = summary

    async def delete_context(self, user_id: str, conv_id: str) -> None:
        key = self._key(user_id, conv_id)
        async with self._lock:
            self._contexts.pop(key, None)
            self._summaries.pop(key, None)

    async def clear_user(self, user_id: str) -> int:
        prefix = f"{user_id}:"
        removed = 0
        async with self._lock:
            keys_to_remove = [k for k in self._contexts if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._contexts[k]
                self._summaries.pop(k, None)
                removed += 1
        logger.info("InMemoryStore: cleared %d conversations for user %s", removed, user_id)
        return removed

    # ── Extra helpers ─────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "total_conversations": len(self._contexts),
                "total_summaries": len(self._summaries),
                "max_conversations": MAX_CONVERSATIONS,
            }

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _evict_if_needed(self) -> None:
        """Evict the least-recently-used entries when limit is exceeded."""
        while len(self._contexts) > MAX_CONVERSATIONS:
            oldest_key, _ = self._contexts.popitem(last=False)
            self._summaries.pop(oldest_key, None)
            logger.debug("InMemoryStore: evicted LRU conversation %s", oldest_key)


__all__ = ["InMemoryStore"]

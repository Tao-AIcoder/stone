"""
tests/test_module_memory_inmemory.py - Unit tests for InMemoryStore (short-term).

Tests each method independently, verifying:
- get/save/delete context
- get/save summary
- clear_user returns count
- LRU eviction when capacity is exceeded
- asyncio.Lock: concurrent writes don't corrupt state
"""

from __future__ import annotations

import sys
import os
import asyncio

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.memory.inmemory_store import InMemoryStore
from modules.interfaces.memory import ShortTermMemoryInterface


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


MESSAGES = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there"},
]


# ── Interface compliance ───────────────────────────────────────────────────────

class TestInterface:
    def test_inherits_short_term_interface(self) -> None:
        assert issubclass(InMemoryStore, ShortTermMemoryInterface)

    def test_has_all_required_methods(self) -> None:
        store = InMemoryStore()
        for method in ("get_context", "save_context", "get_summary",
                       "save_summary", "delete_context", "clear_user"):
            assert callable(getattr(store, method))


# ── get_context / save_context ────────────────────────────────────────────────

class TestContext:
    @pytest.mark.asyncio
    async def test_get_context_returns_none_when_empty(self, store: InMemoryStore) -> None:
        result = await store.get_context("user1", "conv1")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_then_get_context(self, store: InMemoryStore) -> None:
        await store.save_context("user1", "conv1", MESSAGES)
        result = await store.get_context("user1", "conv1")
        assert result == MESSAGES

    @pytest.mark.asyncio
    async def test_different_users_are_isolated(self, store: InMemoryStore) -> None:
        await store.save_context("user1", "conv1", MESSAGES)
        result = await store.get_context("user2", "conv1")
        assert result is None

    @pytest.mark.asyncio
    async def test_different_conv_ids_are_isolated(self, store: InMemoryStore) -> None:
        await store.save_context("user1", "conv1", MESSAGES)
        result = await store.get_context("user1", "conv2")
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite_context(self, store: InMemoryStore) -> None:
        await store.save_context("user1", "conv1", MESSAGES)
        new_msgs = [{"role": "user", "content": "Updated"}]
        await store.save_context("user1", "conv1", new_msgs)
        result = await store.get_context("user1", "conv1")
        assert result == new_msgs

    @pytest.mark.asyncio
    async def test_get_returns_same_data(self, store: InMemoryStore) -> None:
        msgs = [{"role": "user", "content": "Hello"}]
        await store.save_context("user1", "conv1", msgs)
        result = await store.get_context("user1", "conv1")
        assert result[0]["content"] == "Hello"


# ── delete_context ────────────────────────────────────────────────────────────

class TestDeleteContext:
    @pytest.mark.asyncio
    async def test_delete_removes_context(self, store: InMemoryStore) -> None:
        await store.save_context("user1", "conv1", MESSAGES)
        await store.delete_context("user1", "conv1")
        result = await store.get_context("user1", "conv1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(self, store: InMemoryStore) -> None:
        await store.delete_context("user1", "nonexistent")  # should not raise


# ── get_summary / save_summary ────────────────────────────────────────────────

class TestSummary:
    @pytest.mark.asyncio
    async def test_get_summary_returns_none_when_empty(self, store: InMemoryStore) -> None:
        result = await store.get_summary("user1", "conv1")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_then_get_summary(self, store: InMemoryStore) -> None:
        await store.save_summary("user1", "conv1", "User asked about weather.")
        result = await store.get_summary("user1", "conv1")
        assert result == "User asked about weather."

    @pytest.mark.asyncio
    async def test_overwrite_summary(self, store: InMemoryStore) -> None:
        await store.save_summary("user1", "conv1", "old")
        await store.save_summary("user1", "conv1", "new")
        result = await store.get_summary("user1", "conv1")
        assert result == "new"


# ── clear_user ────────────────────────────────────────────────────────────────

class TestClearUser:
    @pytest.mark.asyncio
    async def test_clear_user_returns_count(self, store: InMemoryStore) -> None:
        await store.save_context("user1", "conv1", MESSAGES)
        await store.save_context("user1", "conv2", MESSAGES)
        count = await store.clear_user("user1")
        assert count == 2

    @pytest.mark.asyncio
    async def test_clear_user_removes_all_convs(self, store: InMemoryStore) -> None:
        await store.save_context("user1", "conv1", MESSAGES)
        await store.save_context("user1", "conv2", MESSAGES)
        await store.clear_user("user1")
        assert await store.get_context("user1", "conv1") is None
        assert await store.get_context("user1", "conv2") is None

    @pytest.mark.asyncio
    async def test_clear_user_does_not_affect_other_users(self, store: InMemoryStore) -> None:
        await store.save_context("user1", "conv1", MESSAGES)
        await store.save_context("user2", "conv1", MESSAGES)
        await store.clear_user("user1")
        result = await store.get_context("user2", "conv1")
        assert result == MESSAGES

    @pytest.mark.asyncio
    async def test_clear_nonexistent_user_returns_zero(self, store: InMemoryStore) -> None:
        count = await store.clear_user("ghost_user")
        assert count == 0


from modules.memory import inmemory_store as _imm_mod


# ── LRU eviction ─────────────────────────────────────────────────────────────

class TestLRUEviction:
    @pytest.mark.asyncio
    async def test_evicts_oldest_when_capacity_exceeded(self, monkeypatch) -> None:
        monkeypatch.setattr(_imm_mod, "MAX_CONVERSATIONS", 2)
        store = InMemoryStore()
        await store.save_context("user1", "conv1", MESSAGES)
        await store.save_context("user1", "conv2", MESSAGES)
        await store.save_context("user1", "conv3", MESSAGES)  # evicts conv1
        assert await store.get_context("user1", "conv1") is None
        assert await store.get_context("user1", "conv3") == MESSAGES


# ── Concurrency ───────────────────────────────────────────────────────────────

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_writes_do_not_corrupt(self) -> None:
        store = InMemoryStore()
        msgs_a = [{"role": "user", "content": "A"}]
        msgs_b = [{"role": "user", "content": "B"}]

        async def write_a():
            for _ in range(20):
                await store.save_context("user1", "conv1", msgs_a)

        async def write_b():
            for _ in range(20):
                await store.save_context("user1", "conv1", msgs_b)

        await asyncio.gather(write_a(), write_b())
        result = await store.get_context("user1", "conv1")
        # Result must be one of the two valid values
        assert result in (msgs_a, msgs_b)

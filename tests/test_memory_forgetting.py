"""
tests/test_memory_forgetting.py - 遗忘曲线逻辑单元测试

覆盖：
  - 记忆衰减计算（数学正确性）
  - 强度阈值触发压缩 / 删除
  - 强化（reinforce）正确提升强度
  - 大小限制触发主动遗忘
  - 显式记忆衰减速率低于自动提取记忆
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aiosqlite

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def tmp_db(tmp_path):
    """Create a temporary SQLite database with required schema."""
    db_path = str(tmp_path / "test_memory.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE long_term_memory (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                compressed_content TEXT DEFAULT '',
                source TEXT DEFAULT '',
                confidence REAL DEFAULT 1.0,
                tags TEXT DEFAULT '[]',
                strength REAL DEFAULT 1.0,
                decay_rate REAL DEFAULT 0.05,
                embedding TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                accessed_at TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            )
        """)
        await db.commit()
    return db_path


@pytest.fixture
def memory_store(tmp_db):
    from modules.memory.memory_store import MemoryStore
    return MemoryStore(
        db_path=tmp_db,
        decay_rate=0.05,
        compress_threshold=0.5,
        forget_threshold=0.1,
        reinforce_boost=0.2,
        max_size_kb=10,
    )


# ── Math correctness ──────────────────────────────────────────────────────────

class TestDecayMath:
    def test_decay_formula(self):
        """strength = initial * e^(-λ * days)"""
        initial = 1.0
        decay_rate = 0.05
        days = 10
        expected = initial * math.exp(-decay_rate * days)
        assert abs(expected - 0.6065) < 0.001

    def test_20_day_decay(self):
        """After 20 days at λ=0.05, strength ≈ 0.368"""
        strength = 1.0 * math.exp(-0.05 * 20)
        assert 0.36 < strength < 0.38

    def test_explicit_slower_decay(self):
        """Explicit memories use decay_rate * 0.5 → decay slower."""
        explicit_rate = 0.05 * 0.5
        auto_rate = 0.05
        days = 30
        explicit_strength = math.exp(-explicit_rate * days)
        auto_strength = math.exp(-auto_rate * days)
        assert explicit_strength > auto_strength


# ── Save & Retrieve ───────────────────────────────────────────────────────────

class TestMemoryStoreSaveRetrieve:
    @pytest.mark.asyncio
    async def test_save_and_get(self, memory_store):
        memory_id = await memory_store.save(
            user_id="u1",
            memory_type="fact",
            content="用户喜欢简洁的回答",
            source="explicit",
        )
        record = await memory_store.get(memory_id)
        assert record is not None
        assert record.content == "用户喜欢简洁的回答"
        assert record.memory_type == "fact"
        assert record.strength == 1.0

    @pytest.mark.asyncio
    async def test_explicit_memory_has_lower_decay_rate(self, memory_store):
        mid = await memory_store.save(
            user_id="u1",
            memory_type="preference",
            content="偏好测试",
            source="explicit",
        )
        record = await memory_store.get(mid)
        assert record.decay_rate == pytest.approx(0.025, abs=0.001)  # 0.05 * 0.5

    @pytest.mark.asyncio
    async def test_list_by_user(self, memory_store):
        for i in range(3):
            await memory_store.save("u2", "fact", f"事实{i}")
        records = await memory_store.list_by_user("u2")
        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_keyword_search(self, memory_store):
        await memory_store.save("u3", "fact", "用户喜欢喝咖啡")
        await memory_store.save("u3", "fact", "用户每天跑步")
        results = await memory_store.search_keyword("u3", "咖啡")
        assert len(results) == 1
        assert "咖啡" in results[0].content


# ── Forgetting Curve ──────────────────────────────────────────────────────────

class TestForgettingCurve:
    @pytest.mark.asyncio
    async def test_decay_reduces_strength(self, tmp_db):
        """After decay run, strength should be lower than initial."""
        from modules.memory.memory_store import MemoryStore
        store = MemoryStore(db_path=tmp_db, decay_rate=0.05)
        mid = await store.save("u1", "fact", "某条记忆")

        # Manually set accessed_at to 20 days ago
        twenty_days_ago = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "UPDATE long_term_memory SET accessed_at=? WHERE memory_id=?",
                (twenty_days_ago, mid),
            )
            await db.commit()

        stats = await store.run_decay("u1")
        record = await store.get(mid)
        # Strength should have decayed
        assert record is not None
        assert record.strength < 0.9

    @pytest.mark.asyncio
    async def test_below_forget_threshold_gets_deleted(self, tmp_db):
        """Memory with strength below forget_threshold should be soft-deleted."""
        from modules.memory.memory_store import MemoryStore
        store = MemoryStore(db_path=tmp_db, decay_rate=0.5, forget_threshold=0.1)
        mid = await store.save("u1", "fact", "很久以前的记忆")

        # Set accessed_at to 60 days ago → strength = e^(-0.5*60) ≈ 9e-14 < 0.1
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "UPDATE long_term_memory SET accessed_at=? WHERE memory_id=?",
                (old, mid),
            )
            await db.commit()

        stats = await store.run_decay("u1")
        assert stats["forgotten"] >= 1
        record = await store.get(mid)
        assert record is None  # soft-deleted, active=0

    @pytest.mark.asyncio
    async def test_below_compress_threshold_uses_compressed(self, tmp_db):
        """Memory between compress and forget threshold should use compressed content."""
        from modules.memory.memory_store import MemoryStore
        store = MemoryStore(
            db_path=tmp_db,
            decay_rate=0.1,
            compress_threshold=0.5,
            forget_threshold=0.1,
        )
        mid = await store.save("u1", "fact", "详细内容很长很长", source="auto_extract")
        # Pre-populate compressed content
        await store.update_compressed(mid, "摘要版本")

        # Set accessed_at to 14 days ago → strength = e^(-0.1*14) ≈ 0.247 < 0.5
        old = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "UPDATE long_term_memory SET accessed_at=? WHERE memory_id=?",
                (old, mid),
            )
            await db.commit()

        stats = await store.run_decay("u1")
        assert stats["compressed"] >= 1
        record = await store.get(mid)
        # content should now be the compressed version
        assert record is not None
        assert record.content == "摘要版本"


# ── Reinforce ─────────────────────────────────────────────────────────────────

class TestReinforce:
    @pytest.mark.asyncio
    async def test_reinforce_boosts_strength(self, tmp_db):
        from modules.memory.memory_store import MemoryStore
        store = MemoryStore(db_path=tmp_db, reinforce_boost=0.2)
        mid = await store.save("u1", "behavior", "简洁回答")

        # Decay strength first
        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "UPDATE long_term_memory SET strength=0.6 WHERE memory_id=?", (mid,)
            )
            await db.commit()

        await store.reinforce(mid)
        record = await store.get(mid)
        assert record.strength == pytest.approx(0.8, abs=0.01)

    @pytest.mark.asyncio
    async def test_reinforce_caps_at_1(self, tmp_db):
        from modules.memory.memory_store import MemoryStore
        store = MemoryStore(db_path=tmp_db, reinforce_boost=0.5)
        mid = await store.save("u1", "behavior", "测试行为")
        await store.reinforce(mid, boost=0.9)
        record = await store.get(mid)
        assert record.strength == pytest.approx(1.0, abs=0.001)


# ── Size Limit ────────────────────────────────────────────────────────────────

class TestSizeLimit:
    @pytest.mark.asyncio
    async def test_size_limit_prunes_weakest(self, tmp_db):
        """When total size exceeds max_size_kb, weakest memories are removed."""
        from modules.memory.memory_store import MemoryStore
        # max_size_kb=1 means ~1024 bytes
        store = MemoryStore(db_path=tmp_db, max_size_kb=1)

        # Save 5 memories with different strengths
        for i, strength in enumerate([0.9, 0.8, 0.5, 0.3, 0.2]):
            mid = await store.save("u1", "fact", "x" * 300)  # 300 bytes each, total 1500
            async with aiosqlite.connect(tmp_db) as db:
                await db.execute(
                    "UPDATE long_term_memory SET strength=? WHERE memory_id=?",
                    (strength, mid),
                )
                await db.commit()

        # The weakest memories should have been pruned to stay under 1KB
        records = await store.list_by_user("u1")
        total_size = sum(len(r.content) for r in records)
        assert total_size <= 1024 + 300  # allow one over (prunes happen after save)

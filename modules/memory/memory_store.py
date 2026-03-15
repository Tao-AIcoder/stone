"""
modules/memory/memory_store.py - Long-term memory with forgetting curve for STONE.

Each memory record has a strength value (0.0~1.0) that decays over time:
  strength(t) = initial * e^(-decay_rate * days_elapsed)

Strength thresholds (configurable):
  >= compress_threshold (0.5): full content preserved
  >= forget_threshold   (0.1): compressed content only
  <  forget_threshold   (0.1): record deleted (forgotten)

Accessing or reinforcing a memory resets / boosts its strength.
A weekly maintenance job runs decay + cleanup.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from config import settings

logger = logging.getLogger(__name__)

# Default forgetting curve parameters (overridable via stone.config.json)
DEFAULT_DECAY_RATE = 0.05           # λ per day
DEFAULT_COMPRESS_THRESHOLD = 0.5   # below this → use compressed_content
DEFAULT_FORGET_THRESHOLD = 0.1     # below this → delete
DEFAULT_REINFORCE_BOOST = 0.2      # strength boost on positive feedback
DEFAULT_MAX_SIZE_KB = 512          # total memory size cap per user


@dataclass
class MemoryRecord:
    memory_id: str
    user_id: str
    memory_type: str          # entity | preference | fact | behavior | note
    content: str              # full content
    compressed_content: str   # summarised (populated when strength drops)
    strength: float           # 0.0 ~ 1.0
    decay_rate: float         # per-record λ (explicit memories decay slower)
    source: str               # auto_extract | explicit | reinforcement
    tags: list[str]
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    embedding: list[float] = field(default_factory=list)


class MemoryStore:
    """
    Manages long-term memories with forgetting curve logic.

    Backed by the existing SQLite database (long_term_memory table extended
    with strength / decay_rate / compressed_content columns).
    """

    def __init__(
        self,
        db_path: str | None = None,
        decay_rate: float = DEFAULT_DECAY_RATE,
        compress_threshold: float = DEFAULT_COMPRESS_THRESHOLD,
        forget_threshold: float = DEFAULT_FORGET_THRESHOLD,
        reinforce_boost: float = DEFAULT_REINFORCE_BOOST,
        max_size_kb: int = DEFAULT_MAX_SIZE_KB,
    ) -> None:
        self._db_path = db_path or str(settings.database_url).replace("sqlite:///", "")
        self._decay_rate = decay_rate
        self._compress_threshold = compress_threshold
        self._forget_threshold = forget_threshold
        self._reinforce_boost = reinforce_boost
        self._max_size_kb = max_size_kb

    # ── Schema ────────────────────────────────────────────────────────────────

    async def ensure_schema(self) -> None:
        """Add forgetting-curve columns if they don't exist yet (migration-safe)."""
        async with aiosqlite.connect(self._db_path) as db:
            # Add new columns; ignore errors if they already exist
            for col_def in [
                "ALTER TABLE long_term_memory ADD COLUMN strength REAL DEFAULT 1.0",
                "ALTER TABLE long_term_memory ADD COLUMN decay_rate REAL DEFAULT 0.05",
                "ALTER TABLE long_term_memory ADD COLUMN compressed_content TEXT DEFAULT ''",
                "ALTER TABLE long_term_memory ADD COLUMN embedding TEXT DEFAULT '[]'",
            ]:
                try:
                    await db.execute(col_def)
                except Exception:
                    pass  # column already exists
            await db.commit()

    # ── Write ─────────────────────────────────────────────────────────────────

    async def save(
        self,
        user_id: str,
        memory_type: str,
        content: str,
        source: str = "auto_extract",
        tags: list[str] | None = None,
        initial_strength: float = 1.0,
        decay_rate: float | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        """Save a new memory. Returns memory_id."""
        memory_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        # Explicit memories ("请记住") decay slower
        effective_decay = decay_rate if decay_rate is not None else (
            self._decay_rate * 0.5 if source == "explicit" else self._decay_rate
        )
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO long_term_memory
                  (memory_id, user_id, category, content, compressed_content,
                   source, confidence, tags, strength, decay_rate, embedding,
                   created_at, updated_at, accessed_at, access_count, active)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    memory_id, user_id, memory_type, content, "",
                    source, initial_strength, json.dumps(tags or [], ensure_ascii=False),
                    initial_strength, effective_decay,
                    json.dumps(embedding or [], ensure_ascii=False),
                    now, now, now, 0, 1,
                ),
            )
            await db.commit()
        await self._enforce_size_limit(user_id)
        logger.debug("Memory saved: %s (%s)", memory_id[:8], memory_type)
        return memory_id

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, memory_id: str) -> MemoryRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM long_term_memory WHERE memory_id=? AND active=1",
                (memory_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    async def list_by_user(
        self,
        user_id: str,
        memory_type: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        """Return active memories for a user, newest first."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if memory_type:
                sql = (
                    "SELECT * FROM long_term_memory "
                    "WHERE user_id=? AND category=? AND active=1 "
                    "ORDER BY accessed_at DESC LIMIT ?"
                )
                params = (user_id, memory_type, limit)
            else:
                sql = (
                    "SELECT * FROM long_term_memory "
                    "WHERE user_id=? AND active=1 "
                    "ORDER BY accessed_at DESC LIMIT ?"
                )
                params = (user_id, limit)
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def search_keyword(
        self,
        user_id: str,
        query: str,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Keyword search across memory content."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM long_term_memory
                WHERE user_id=? AND active=1
                  AND (content LIKE ? OR compressed_content LIKE ?)
                ORDER BY strength DESC, accessed_at DESC
                LIMIT ?
                """,
                (user_id, f"%{query}%", f"%{query}%", limit),
            ) as cur:
                rows = await cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    # ── Access & Reinforcement ────────────────────────────────────────────────

    async def touch(self, memory_id: str) -> None:
        """Mark a memory as accessed (boosts effective strength by resetting timer)."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE long_term_memory
                SET accessed_at=?, access_count=access_count+1
                WHERE memory_id=?
                """,
                (now, memory_id),
            )
            await db.commit()

    async def reinforce(self, memory_id: str, boost: float | None = None) -> None:
        """
        Boost a memory's strength (e.g. user praised the AI's behaviour).
        Strength is capped at 1.0. Last-accessed timestamp is also reset.
        """
        delta = boost if boost is not None else self._reinforce_boost
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE long_term_memory
                SET strength = MIN(1.0, strength + ?),
                    accessed_at = ?,
                    access_count = access_count + 1
                WHERE memory_id = ?
                """,
                (delta, now, memory_id),
            )
            await db.commit()
        logger.debug("Memory reinforced: %s +%.2f", memory_id[:8], delta)

    async def update_compressed(self, memory_id: str, compressed: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE long_term_memory SET compressed_content=?, updated_at=? WHERE memory_id=?",
                (compressed, now, memory_id),
            )
            await db.commit()

    # ── Forgetting Curve Maintenance ──────────────────────────────────────────

    async def run_decay(self, user_id: str | None = None) -> dict[str, int]:
        """
        Apply forgetting curve decay to all active memories.
        - Strength drops based on days since last_accessed
        - Below compress_threshold → content replaced by compressed_content (if available)
        - Below forget_threshold → record soft-deleted

        Returns counts: {decayed, compressed, forgotten}
        """
        now = datetime.now(timezone.utc)
        stats = {"decayed": 0, "compressed": 0, "forgotten": 0}

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            where = "WHERE active=1" + (" AND user_id=?" if user_id else "")
            params = (user_id,) if user_id else ()
            async with db.execute(
                f"SELECT * FROM long_term_memory {where}", params
            ) as cur:
                rows = await cur.fetchall()

            for row in rows:
                last = datetime.fromisoformat(row["accessed_at"].replace("Z", "+00:00"))
                days = (now - last).total_seconds() / 86400
                decay_rate = row["decay_rate"] or self._decay_rate
                new_strength = (row["strength"] or 1.0) * math.exp(-decay_rate * days)

                if new_strength < self._forget_threshold:
                    await db.execute(
                        "UPDATE long_term_memory SET active=0, strength=? WHERE memory_id=?",
                        (new_strength, row["memory_id"]),
                    )
                    stats["forgotten"] += 1

                elif new_strength < self._compress_threshold:
                    compressed = row["compressed_content"] or ""
                    if compressed:
                        await db.execute(
                            "UPDATE long_term_memory SET strength=?, content=? WHERE memory_id=?",
                            (new_strength, compressed, row["memory_id"]),
                        )
                    else:
                        await db.execute(
                            "UPDATE long_term_memory SET strength=? WHERE memory_id=?",
                            (new_strength, row["memory_id"]),
                        )
                    stats["compressed"] += 1

                else:
                    await db.execute(
                        "UPDATE long_term_memory SET strength=? WHERE memory_id=?",
                        (new_strength, row["memory_id"]),
                    )
                    stats["decayed"] += 1

            await db.commit()

        logger.info("Memory decay run: %s", stats)
        return stats

    async def list_active_users(self) -> list[str]:
        """Return distinct user_ids that have at least one active memory."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT DISTINCT user_id FROM long_term_memory WHERE active=1"
            ) as cursor:
                rows = await cursor.fetchall()
        return [row[0] for row in rows]

    # ── Size Limit Enforcement ────────────────────────────────────────────────

    async def _enforce_size_limit(self, user_id: str) -> None:
        """
        If total memory content exceeds max_size_kb, delete weakest memories first.
        """
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """
                SELECT memory_id, LENGTH(content) as sz, strength
                FROM long_term_memory
                WHERE user_id=? AND active=1
                ORDER BY strength ASC
                """,
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()

        total_bytes = sum(r[1] for r in rows)
        limit_bytes = self._max_size_kb * 1024

        if total_bytes <= limit_bytes:
            return

        # Delete weakest memories until under limit
        to_delete: list[str] = []
        for memory_id, sz, _ in rows:
            if total_bytes <= limit_bytes:
                break
            to_delete.append(memory_id)
            total_bytes -= sz

        if to_delete:
            async with aiosqlite.connect(self._db_path) as db:
                placeholders = ",".join("?" * len(to_delete))
                await db.execute(
                    f"UPDATE long_term_memory SET active=0 WHERE memory_id IN ({placeholders})",
                    to_delete,
                )
                await db.commit()
            logger.info("Memory size limit: pruned %d records", len(to_delete))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _row_to_record(self, row: Any) -> MemoryRecord:
        tags = json.loads(row["tags"] or "[]")
        embedding = json.loads(row["embedding"] or "[]")
        return MemoryRecord(
            memory_id=row["memory_id"],
            user_id=row["user_id"],
            memory_type=row["category"],
            content=row["content"],
            compressed_content=row["compressed_content"] or "",
            strength=row["strength"] or 1.0,
            decay_rate=row["decay_rate"] or self._decay_rate,
            source=row["source"] or "auto_extract",
            tags=tags,
            created_at=datetime.fromisoformat(
                row["created_at"].replace("Z", "+00:00")
            ),
            last_accessed=datetime.fromisoformat(
                row["accessed_at"].replace("Z", "+00:00")
            ),
            access_count=row["access_count"] or 0,
            embedding=embedding,
        )


__all__ = ["MemoryRecord", "MemoryStore"]

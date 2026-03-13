"""
modules/memory/sqlite_store.py - SQLite long-term storage for STONE (默行者)

Creates and manages all database tables.
All SQL uses parameterized queries to prevent injection.
Uses aiosqlite for async operations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from config import settings
from models.audit import AuditLog, SecurityLog
from models.conversation import Message, MessageRole
from models.memory import Memory, MemoryCategory
from modules.interfaces.memory import LongTermMemoryInterface

logger = logging.getLogger(__name__)

CREATE_TABLES_SQL = [
    # ── Conversations ─────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS conversations (
        conv_id     TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        title       TEXT DEFAULT '',
        status      TEXT DEFAULT 'active',
        summary     TEXT DEFAULT '',
        message_count INTEGER DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    # ── Messages ──────────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS messages (
        message_id  TEXT PRIMARY KEY,
        conv_id     TEXT NOT NULL,
        user_id     TEXT NOT NULL,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        tool_name   TEXT DEFAULT '',
        tool_call_id TEXT DEFAULT '',
        token_count INTEGER DEFAULT 0,
        timestamp   TEXT NOT NULL,
        metadata    TEXT DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conv_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)",
    # ── Long-term Memory ──────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS long_term_memory (
        memory_id   TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        category    TEXT NOT NULL,
        content     TEXT NOT NULL,
        source      TEXT DEFAULT '',
        confidence  REAL DEFAULT 1.0,
        tags        TEXT DEFAULT '[]',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        accessed_at TEXT NOT NULL,
        access_count INTEGER DEFAULT 0,
        active      INTEGER DEFAULT 1
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_user_id ON long_term_memory(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_category ON long_term_memory(category)",
    # ── Audit Log ─────────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        log_id      TEXT PRIMARY KEY,
        timestamp   TEXT NOT NULL,
        level       TEXT NOT NULL,
        action      TEXT NOT NULL,
        user_id     TEXT NOT NULL,
        conv_id     TEXT DEFAULT '',
        detail      TEXT DEFAULT '{}',
        result      TEXT DEFAULT 'success',
        duration_ms REAL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)",
    # ── Security Log ──────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS security_log (
        log_id      TEXT PRIMARY KEY,
        timestamp   TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        source_ip   TEXT DEFAULT '',
        user_id     TEXT DEFAULT '',
        open_id     TEXT DEFAULT '',
        detail      TEXT DEFAULT '',
        severity    TEXT DEFAULT 'WARNING'
    )
    """,
    # ── Scheduled Tasks ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS scheduled_tasks (
        task_id     TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        name        TEXT NOT NULL,
        cron_expr   TEXT NOT NULL,
        action      TEXT NOT NULL,
        enabled     INTEGER DEFAULT 1,
        created_at  TEXT NOT NULL,
        last_run    TEXT
    )
    """,
]


def _now() -> str:
    return datetime.utcnow().isoformat()


class SQLiteStore(LongTermMemoryInterface):
    """Async SQLite store for all STONE persistent data."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        for sql in CREATE_TABLES_SQL:
            await self._db.execute(sql)
        await self._db.commit()
        logger.info("SQLiteStore initialized at %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteStore not initialized. Call initialize() first.")
        return self._db

    # ── Conversations ─────────────────────────────────────────────────────────

    async def get_conversation(self, conv_id: str) -> dict[str, Any] | None:
        async with self.db.execute(
            "SELECT * FROM conversations WHERE conv_id = ?", (conv_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def save_conversation(self, conv_id: str, user_id: str, title: str = "") -> None:
        now = _now()
        await self.db.execute(
            """
            INSERT INTO conversations (conv_id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conv_id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (conv_id, user_id, title, now, now),
        )
        await self.db.commit()

    async def update_conversation_summary(self, conv_id: str, summary: str) -> None:
        await self.db.execute(
            "UPDATE conversations SET summary = ?, updated_at = ? WHERE conv_id = ?",
            (summary, _now(), conv_id),
        )
        await self.db.commit()

    async def get_conversation_summary(self, conv_id: str) -> str:
        async with self.db.execute(
            "SELECT summary FROM conversations WHERE conv_id = ?", (conv_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["summary"] if row else ""

    async def list_conversations(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        async with self.db.execute(
            """
            SELECT * FROM conversations
            WHERE user_id = ? AND status != 'deleted'
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ── Messages ──────────────────────────────────────────────────────────────

    async def save_message(self, msg: Message) -> None:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO messages
            (message_id, conv_id, user_id, role, content,
             tool_name, tool_call_id, token_count, timestamp, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.message_id,
                msg.conv_id,
                msg.user_id,
                msg.role.value,
                msg.content,
                msg.tool_name,
                msg.tool_call_id,
                msg.token_count,
                msg.timestamp.isoformat(),
                json.dumps(msg.metadata, ensure_ascii=False),
            ),
        )
        await self.db.execute(
            """
            UPDATE conversations
            SET message_count = message_count + 1, updated_at = ?
            WHERE conv_id = ?
            """,
            (_now(), msg.conv_id),
        )
        await self.db.commit()

    async def get_conversation_messages(
        self, conv_id: str, limit: int = 100, offset: int = 0
    ) -> list[Message]:
        async with self.db.execute(
            """
            SELECT * FROM messages
            WHERE conv_id = ?
            ORDER BY timestamp ASC
            LIMIT ? OFFSET ?
            """,
            (conv_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_message(dict(r)) for r in rows]

    # ── Long-term Memory ──────────────────────────────────────────────────────

    async def save_memory(self, memory: Memory) -> None:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO long_term_memory
            (memory_id, user_id, category, content, source, confidence,
             tags, created_at, updated_at, accessed_at, access_count, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.memory_id,
                memory.user_id,
                memory.category.value,
                memory.content,
                memory.source,
                memory.confidence,
                json.dumps(memory.tags, ensure_ascii=False),
                memory.created_at.isoformat(),
                memory.updated_at.isoformat(),
                memory.accessed_at.isoformat(),
                memory.access_count,
                int(memory.active),
            ),
        )
        await self.db.commit()

    async def get_memories(
        self,
        user_id: str,
        category: MemoryCategory | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        if category:
            async with self.db.execute(
                """
                SELECT * FROM long_term_memory
                WHERE user_id = ? AND category = ? AND active = 1
                ORDER BY accessed_at DESC
                LIMIT ?
                """,
                (user_id, category.value, limit),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self.db.execute(
                """
                SELECT * FROM long_term_memory
                WHERE user_id = ? AND active = 1
                ORDER BY accessed_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_memory(dict(r)) for r in rows]

    async def delete_memory(self, memory_id: str) -> None:
        await self.db.execute(
            "UPDATE long_term_memory SET active = 0 WHERE memory_id = ?",
            (memory_id,),
        )
        await self.db.commit()

    # ── Audit Log ─────────────────────────────────────────────────────────────

    async def save_audit_log(self, log: AuditLog) -> None:
        await self.db.execute(
            """
            INSERT INTO audit_log
            (log_id, timestamp, level, action, user_id, conv_id, detail, result, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.log_id,
                log.timestamp.isoformat(),
                log.level.value,
                log.action,
                log.user_id,
                log.conv_id,
                json.dumps(log.redacted().detail, ensure_ascii=False),
                log.result.value,
                log.duration_ms,
            ),
        )
        await self.db.commit()

    async def get_audit_logs(
        self,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if user_id:
            async with self.db.execute(
                """
                SELECT * FROM audit_log
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self.db.execute(
                "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ── Security Log ──────────────────────────────────────────────────────────

    async def save_security_log(self, log: SecurityLog) -> None:
        await self.db.execute(
            """
            INSERT INTO security_log
            (log_id, timestamp, event_type, source_ip, user_id, open_id, detail, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.log_id,
                log.timestamp.isoformat(),
                log.event_type.value,
                log.source_ip,
                log.user_id,
                log.open_id,
                log.detail,
                log.severity.value,
            ),
        )
        await self.db.commit()

    # ── Scheduled Tasks ───────────────────────────────────────────────────────

    async def save_scheduled_task(
        self,
        task_id: str,
        user_id: str,
        name: str,
        cron_expr: str,
        action: str,
    ) -> None:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO scheduled_tasks
            (task_id, user_id, name, cron_expr, action, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (task_id, user_id, name, cron_expr, action, _now()),
        )
        await self.db.commit()

    async def get_all_scheduled_tasks(self) -> list[dict[str, Any]]:
        async with self.db.execute("SELECT * FROM scheduled_tasks") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_scheduled_task_enabled(self, task_id: str, enabled: bool) -> None:
        await self.db.execute(
            "UPDATE scheduled_tasks SET enabled = ? WHERE task_id = ?",
            (int(enabled), task_id),
        )
        await self.db.commit()

    async def update_scheduled_task_last_run(
        self, task_id: str, last_run: datetime
    ) -> None:
        await self.db.execute(
            "UPDATE scheduled_tasks SET last_run = ? WHERE task_id = ?",
            (last_run.isoformat(), task_id),
        )
        await self.db.commit()

    async def delete_scheduled_task(self, task_id: str) -> None:
        await self.db.execute(
            "DELETE FROM scheduled_tasks WHERE task_id = ?", (task_id,)
        )
        await self.db.commit()


# ── Row converters ────────────────────────────────────────────────────────────

def _row_to_message(row: dict[str, Any]) -> Message:
    return Message(
        message_id=row["message_id"],
        conv_id=row["conv_id"],
        user_id=row["user_id"],
        role=MessageRole(row["role"]),
        content=row["content"],
        tool_name=row.get("tool_name", ""),
        tool_call_id=row.get("tool_call_id", ""),
        token_count=row.get("token_count", 0),
        timestamp=datetime.fromisoformat(row["timestamp"]),
        metadata=json.loads(row.get("metadata", "{}")),
    )


def _row_to_memory(row: dict[str, Any]) -> Memory:
    return Memory(
        memory_id=row["memory_id"],
        user_id=row["user_id"],
        category=MemoryCategory(row["category"]),
        content=row["content"],
        source=row.get("source", ""),
        confidence=row.get("confidence", 1.0),
        tags=json.loads(row.get("tags", "[]")),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        accessed_at=datetime.fromisoformat(row["accessed_at"]),
        access_count=row.get("access_count", 0),
        active=bool(row.get("active", 1)),
    )


__all__ = ["SQLiteStore"]

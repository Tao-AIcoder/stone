"""
modules/note_backends/local_backend.py - Local filesystem note backend for STONE.

Stores notes as files under NOTES_DIR.
Supported formats: .md (default), .txt, .docx (read-only for now)

File naming: {slugified_title}_{uuid8}.{ext}
YAML front matter (markdown only): title, tags, created_at, updated_at, note_id
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings
from modules.interfaces.note_backend import NoteBackendInterface, NoteRecord

logger = logging.getLogger(__name__)

_FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)


def _slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    text = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", text)
    return text[:40].strip("_") or "note"


def _parse_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like front matter from markdown. Returns (meta, body)."""
    m = _FRONT_MATTER_RE.match(raw)
    if not m:
        return {}, raw
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    return meta, m.group(2).strip()


def _build_front_matter(record: NoteRecord) -> str:
    tags_str = json.dumps(record.tags, ensure_ascii=False)
    return (
        f"---\n"
        f"note_id: {record.note_id}\n"
        f"title: \"{record.title}\"\n"
        f"tags: {tags_str}\n"
        f"created_at: {record.created_at}\n"
        f"updated_at: {record.updated_at}\n"
        f"---\n\n"
    )


class LocalNoteBackend(NoteBackendInterface):
    """
    Local filesystem note storage.

    Notes dir: settings.notes_dir (from NOTES_DIR env var)
    Default format: markdown (.md)
    """

    backend_name = "local"

    def __init__(self, notes_dir: str | None = None) -> None:
        self._notes_dir = Path(notes_dir or getattr(settings, "notes_dir", "notes"))
        self._notes_dir.mkdir(parents=True, exist_ok=True)
        # Index: note_id -> filename (in-memory, rebuilt on demand)
        self._index: dict[str, Path] = {}
        self._index_built = False

    def _build_index(self) -> None:
        self._index = {}
        for p in self._notes_dir.glob("*.md"):
            try:
                raw = p.read_text(encoding="utf-8")
                meta, _ = _parse_front_matter(raw)
                nid = meta.get("note_id")
                if nid:
                    self._index[nid] = p
            except Exception:
                pass
        self._index_built = True

    def _get_path(self, note_id: str) -> Path | None:
        if not self._index_built:
            self._build_index()
        return self._index.get(note_id)

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_note(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        fmt: str = "markdown",
    ) -> NoteRecord:
        note_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        ext = ".md" if fmt == "markdown" else ".txt"
        filename = f"{_slugify(title)}_{note_id[:8]}{ext}"
        path = self._notes_dir / filename

        record = NoteRecord(
            note_id=note_id,
            title=title,
            content=content,
            format=fmt,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            source="local",
        )

        if fmt == "markdown":
            file_content = _build_front_matter(record) + content
        else:
            file_content = content

        path.write_text(file_content, encoding="utf-8")
        self._index[note_id] = path
        logger.info("Note created: %s (%s)", filename, note_id[:8])
        return record

    # ── Read ──────────────────────────────────────────────────────────────────

    async def read_note(self, note_id: str) -> NoteRecord | None:
        path = self._get_path(note_id)
        if not path or not path.exists():
            return None
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)
        return NoteRecord(
            note_id=meta.get("note_id", note_id),
            title=meta.get("title", path.stem),
            content=body,
            format="markdown",
            tags=json.loads(meta.get("tags", "[]")) if isinstance(meta.get("tags"), str) else meta.get("tags", []),
            created_at=meta.get("created_at", ""),
            updated_at=meta.get("updated_at", ""),
            source="local",
        )

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_note(
        self,
        note_id: str,
        content: str,
        title: str | None = None,
    ) -> NoteRecord:
        existing = await self.read_note(note_id)
        if not existing:
            raise FileNotFoundError(f"Note not found: {note_id}")
        path = self._get_path(note_id)
        now = datetime.now(timezone.utc).isoformat()
        existing.content = content
        existing.updated_at = now
        if title:
            existing.title = title
        file_content = _build_front_matter(existing) + content
        path.write_text(file_content, encoding="utf-8")  # type: ignore[arg-type]
        return existing

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_note(self, note_id: str) -> bool:
        path = self._get_path(note_id)
        if not path or not path.exists():
            return False
        path.unlink()
        self._index.pop(note_id, None)
        logger.info("Note deleted: %s", note_id[:8])
        return True

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_notes(
        self,
        tag_filter: list[str] | None = None,
        limit: int = 50,
    ) -> list[NoteRecord]:
        if not self._index_built:
            self._build_index()
        records: list[NoteRecord] = []
        for path in sorted(self._notes_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(records) >= limit:
                break
            try:
                raw = path.read_text(encoding="utf-8")
                meta, body = _parse_front_matter(raw)
                tags = json.loads(meta.get("tags", "[]")) if isinstance(meta.get("tags"), str) else []
                if tag_filter and not any(t in tags for t in tag_filter):
                    continue
                records.append(NoteRecord(
                    note_id=meta.get("note_id", path.stem),
                    title=meta.get("title", path.stem),
                    content=body[:200],
                    tags=tags,
                    created_at=meta.get("created_at", ""),
                    updated_at=meta.get("updated_at", ""),
                    source="local",
                ))
            except Exception:
                continue
        return records

    # ── Search ────────────────────────────────────────────────────────────────

    async def search_notes(self, query: str, limit: int = 20) -> list[NoteRecord]:
        if not self._index_built:
            self._build_index()
        query_lower = query.lower()
        results: list[NoteRecord] = []
        for path in self._notes_dir.glob("*.md"):
            if len(results) >= limit:
                break
            try:
                raw = path.read_text(encoding="utf-8")
                if query_lower not in raw.lower():
                    continue
                meta, body = _parse_front_matter(raw)
                results.append(NoteRecord(
                    note_id=meta.get("note_id", path.stem),
                    title=meta.get("title", path.stem),
                    content=body[:300],
                    tags=json.loads(meta.get("tags", "[]")) if isinstance(meta.get("tags"), str) else [],
                    created_at=meta.get("created_at", ""),
                    updated_at=meta.get("updated_at", ""),
                    source="local",
                ))
            except Exception:
                continue
        return results


__all__ = ["LocalNoteBackend"]

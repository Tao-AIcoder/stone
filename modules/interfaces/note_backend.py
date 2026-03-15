"""
modules/interfaces/note_backend.py - Note storage backend ABC for STONE (默行者)

Allows swapping local file storage with cloud MCP backends (Evernote, Baidu Netdisk)
without changing note_tool logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NoteRecord:
    """A single note record."""
    note_id: str
    title: str
    content: str
    format: str = "markdown"          # markdown | text | docx
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    source: str = "local"             # local | evernote | baidu_netdisk
    metadata: dict[str, Any] = field(default_factory=dict)


class NoteBackendInterface(ABC):
    """
    Abstract interface for note storage backends.

    Implementations:
      - LocalNoteBackend   (default, stores .md/.txt/.docx in NOTES_DIR)
      - MCPNoteBackend     (cloud: Evernote CN or Baidu Netdisk via MCP)
    """

    backend_name: str = ""

    @abstractmethod
    async def create_note(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        fmt: str = "markdown",
    ) -> NoteRecord:
        """Create a new note and return the record."""
        ...

    @abstractmethod
    async def read_note(self, note_id: str) -> NoteRecord | None:
        """Read a note by ID. Returns None if not found."""
        ...

    @abstractmethod
    async def update_note(
        self,
        note_id: str,
        content: str,
        title: str | None = None,
    ) -> NoteRecord:
        """Update note content (and optionally title)."""
        ...

    @abstractmethod
    async def delete_note(self, note_id: str) -> bool:
        """Delete a note. Returns True on success."""
        ...

    @abstractmethod
    async def list_notes(
        self,
        tag_filter: list[str] | None = None,
        limit: int = 50,
    ) -> list[NoteRecord]:
        """List notes, optionally filtered by tags."""
        ...

    @abstractmethod
    async def search_notes(self, query: str, limit: int = 20) -> list[NoteRecord]:
        """Search notes by keyword. Returns matching records."""
        ...


__all__ = ["NoteRecord", "NoteBackendInterface"]

"""
modules/note_backends/mcp_backend.py - Cloud note backend via MCP for STONE.

Routes note operations to an MCP Server (Evernote CN or Baidu Netdisk).
The MCP Server handles the actual API calls; this backend adapts the
NoteBackendInterface to MCP tool calls.

Tool name conventions (MCP Server must expose these):
  Evernote:      create_note, get_note, update_note, delete_note, list_notes, search_notes
  Baidu Netdisk: upload_file, download_file, delete_file, list_files, search_files
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from modules.interfaces.note_backend import NoteBackendInterface, NoteRecord

if TYPE_CHECKING:
    from modules.mcp.process_manager import MCPProcessManager

logger = logging.getLogger(__name__)

# Tool name mappings per MCP server type
_TOOL_MAPS: dict[str, dict[str, str]] = {
    "evernote": {
        "create": "create_note",
        "read":   "get_note",
        "update": "update_note",
        "delete": "delete_note",
        "list":   "list_notes",
        "search": "search_notes",
    },
    "baidu_netdisk": {
        "create": "upload_file",
        "read":   "download_file",
        "delete": "delete_file",
        "list":   "list_files",
        "search": "search_files",
    },
}


class MCPNoteBackend(NoteBackendInterface):
    """
    Note backend that stores/retrieves notes via an MCP Server.

    server_name: "evernote" or "baidu_netdisk" (must match stone.config.json key)
    """

    def __init__(
        self,
        mcp_manager: "MCPProcessManager",
        server_name: str = "evernote",
    ) -> None:
        self._mcp = mcp_manager
        self._server_name = server_name
        self._tool_map = _TOOL_MAPS.get(server_name, _TOOL_MAPS["evernote"])

    @property
    def backend_name(self) -> str:
        return self._server_name

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_note(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        fmt: str = "markdown",
    ) -> NoteRecord:
        result = await self._mcp.call(
            self._server_name,
            self._tool_map["create"],
            {"title": title, "content": content, "tags": tags or []},
        )
        if not result.success:
            raise RuntimeError(f"MCP create_note failed: {result.error}")
        # Parse MCP response to extract note_id
        note_id = self._extract_id(result.content) or str(uuid.uuid4())
        now = self._now()
        return NoteRecord(
            note_id=note_id,
            title=title,
            content=content,
            format=fmt,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            source=self._server_name,
            metadata={"mcp_response": str(result.content)[:200]},
        )

    # ── Read ──────────────────────────────────────────────────────────────────

    async def read_note(self, note_id: str) -> NoteRecord | None:
        result = await self._mcp.call(
            self._server_name,
            self._tool_map["read"],
            {"note_id": note_id},
        )
        if not result.success:
            return None
        content = result.content
        if isinstance(content, dict):
            return NoteRecord(
                note_id=note_id,
                title=content.get("title", ""),
                content=content.get("content", str(content)),
                tags=content.get("tags", []),
                created_at=content.get("created_at", ""),
                updated_at=content.get("updated_at", ""),
                source=self._server_name,
            )
        return NoteRecord(
            note_id=note_id,
            title="",
            content=str(content),
            source=self._server_name,
        )

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_note(
        self,
        note_id: str,
        content: str,
        title: str | None = None,
    ) -> NoteRecord:
        args: dict[str, Any] = {"note_id": note_id, "content": content}
        if title:
            args["title"] = title
        result = await self._mcp.call(
            self._server_name,
            self._tool_map["update"],
            args,
        )
        if not result.success:
            raise RuntimeError(f"MCP update_note failed: {result.error}")
        return NoteRecord(
            note_id=note_id,
            title=title or "",
            content=content,
            updated_at=self._now(),
            source=self._server_name,
        )

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_note(self, note_id: str) -> bool:
        result = await self._mcp.call(
            self._server_name,
            self._tool_map["delete"],
            {"note_id": note_id},
        )
        return result.success

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_notes(
        self,
        tag_filter: list[str] | None = None,
        limit: int = 50,
    ) -> list[NoteRecord]:
        args: dict[str, Any] = {"limit": limit}
        if tag_filter:
            args["tags"] = tag_filter
        result = await self._mcp.call(
            self._server_name,
            self._tool_map["list"],
            args,
        )
        if not result.success:
            return []
        return self._parse_list(result.content)

    # ── Search ────────────────────────────────────────────────────────────────

    async def search_notes(self, query: str, limit: int = 20) -> list[NoteRecord]:
        result = await self._mcp.call(
            self._server_name,
            self._tool_map["search"],
            {"query": query, "limit": limit},
        )
        if not result.success:
            return []
        return self._parse_list(result.content)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_id(self, content: Any) -> str:
        """Try to extract a note_id / guid from MCP response."""
        if isinstance(content, dict):
            return str(content.get("note_id") or content.get("guid") or content.get("id") or "")
        if isinstance(content, str):
            # Look for UUID-like pattern
            import re
            m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", content)
            return m.group(0) if m else ""
        return ""

    def _parse_list(self, content: Any) -> list[NoteRecord]:
        if isinstance(content, list):
            records: list[NoteRecord] = []
            for item in content:
                if isinstance(item, dict):
                    records.append(NoteRecord(
                        note_id=str(item.get("note_id") or item.get("guid") or item.get("id") or uuid.uuid4()),
                        title=item.get("title", ""),
                        content=item.get("content", item.get("summary", "")),
                        tags=item.get("tags", []),
                        created_at=item.get("created_at", ""),
                        updated_at=item.get("updated_at", ""),
                        source=self._server_name,
                    ))
            return records
        return []


__all__ = ["MCPNoteBackend"]

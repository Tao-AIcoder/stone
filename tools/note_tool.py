"""
tools/note_tool.py - Note management tool for STONE (默行者)

Supports local and cloud (MCP) backends.
Default: local filesystem (NOTES_DIR).
Cloud routing: triggered by explicit keywords ("存到印象笔记", "存到百度网盘")
or by context/params.

Actions: create_note, read_note, update_note, delete_note, list_notes, search_notes
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from tools.base import ToolInterface, ToolResult

if TYPE_CHECKING:
    from modules.mcp.process_manager import MCPProcessManager
    from modules.note_backends.local_backend import LocalNoteBackend

logger = logging.getLogger(__name__)

_VALID_ACTIONS = (
    "create_note", "read_note", "update_note",
    "delete_note", "list_notes", "search_notes",
)

# Keywords that trigger cloud backend routing
_EVERNOTE_KEYWORDS = ["印象笔记", "evernote", "印象"]
_BAIDU_KEYWORDS = ["百度网盘", "baidu", "网盘"]


def _detect_cloud_backend(params: dict[str, Any]) -> str | None:
    """
    Return cloud backend name if params contain cloud keywords, else None.
    Checks: backend param, title, content, tags.
    """
    explicit = params.get("backend", "").lower()
    if "evernote" in explicit or "印象" in explicit:
        return "evernote"
    if "baidu" in explicit or "网盘" in explicit:
        return "baidu_netdisk"

    text_to_scan = " ".join([
        str(params.get("title", "")),
        str(params.get("content", "")),
        " ".join(params.get("tags", [])),
    ]).lower()

    for kw in _EVERNOTE_KEYWORDS:
        if kw in text_to_scan:
            return "evernote"
    for kw in _BAIDU_KEYWORDS:
        if kw in text_to_scan:
            return "baidu_netdisk"
    return None


class NoteTool(ToolInterface):
    """
    Note management with local/cloud backend routing.

    Backend selection priority:
      1. params["backend"] explicit value
      2. Keyword detection in title/content/tags
      3. Default: local
    """

    name = "note_tool"
    description = (
        "管理笔记：创建、读取、更新、删除、列举、搜索。"
        "支持本地存储和云端（印象笔记/百度网盘）。"
    )
    requires_confirmation = False

    def __init__(
        self,
        local_backend: "LocalNoteBackend",
        mcp_manager: "MCPProcessManager | None" = None,
    ) -> None:
        self._local = local_backend
        self._mcp_manager = mcp_manager

    def needs_confirmation_for(self, params: dict) -> bool:
        return params.get("action") == "delete_note"

    def _get_backend(self, params: dict[str, Any]) -> Any:
        """Return the appropriate note backend for this request."""
        cloud = _detect_cloud_backend(params)
        if cloud and self._mcp_manager:
            from modules.note_backends.mcp_backend import MCPNoteBackend
            return MCPNoteBackend(self._mcp_manager, server_name=cloud)
        return self._local

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        action = params.get("action", "")
        if action not in _VALID_ACTIONS:
            return ToolResult.fail(
                f"不支持的 action: {action!r}。"
                f"合法 action: {', '.join(_VALID_ACTIONS)}"
            )
        backend = self._get_backend(params)
        handler = getattr(self, f"_action_{action}")
        return await handler(params, backend, user_id)

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _action_create_note(
        self, params: dict[str, Any], backend: Any, user_id: str
    ) -> ToolResult:
        title = params.get("title", "").strip()
        content = params.get("content", "").strip()
        tags = params.get("tags", [])
        fmt = params.get("format", "markdown")
        if not title:
            return ToolResult.fail("title 不能为空")
        try:
            record = await backend.create_note(title, content, tags=tags, fmt=fmt)
            return ToolResult.ok(
                f"笔记已创建：《{record.title}》（{record.source}）",
                {"note_id": record.note_id, "backend": record.source},
            )
        except Exception as exc:
            return ToolResult.fail(f"创建笔记失败: {exc}")

    async def _action_read_note(
        self, params: dict[str, Any], backend: Any, user_id: str
    ) -> ToolResult:
        note_id = params.get("note_id", "").strip()
        if not note_id:
            return ToolResult.fail("note_id 不能为空")
        record = await backend.read_note(note_id)
        if not record:
            return ToolResult.fail(f"未找到笔记: {note_id}")
        output = f"## {record.title}\n\n{record.content}"
        if record.tags:
            output += f"\n\n标签: {', '.join(record.tags)}"
        return ToolResult.ok(output, {"note_id": record.note_id})

    async def _action_update_note(
        self, params: dict[str, Any], backend: Any, user_id: str
    ) -> ToolResult:
        note_id = params.get("note_id", "").strip()
        content = params.get("content", "").strip()
        title = params.get("title")
        if not note_id:
            return ToolResult.fail("note_id 不能为空")
        try:
            record = await backend.update_note(note_id, content, title=title)
            return ToolResult.ok(f"笔记已更新：《{record.title or note_id}》")
        except Exception as exc:
            return ToolResult.fail(f"更新笔记失败: {exc}")

    async def _action_delete_note(
        self, params: dict[str, Any], backend: Any, user_id: str
    ) -> ToolResult:
        note_id = params.get("note_id", "").strip()
        if not note_id:
            return ToolResult.fail("note_id 不能为空")
        success = await backend.delete_note(note_id)
        if success:
            return ToolResult.ok(f"笔记已删除: {note_id}")
        return ToolResult.fail(f"删除失败，笔记不存在: {note_id}")

    async def _action_list_notes(
        self, params: dict[str, Any], backend: Any, user_id: str
    ) -> ToolResult:
        tags = params.get("tags") or None
        limit = int(params.get("limit", 20))
        notes = await backend.list_notes(tag_filter=tags, limit=limit)
        if not notes:
            return ToolResult.ok("暂无笔记。")
        lines = [f"• [{r.note_id[:8]}] {r.title}" + (f"  [{', '.join(r.tags)}]" if r.tags else "") for r in notes]
        return ToolResult.ok(
            f"共 {len(notes)} 条笔记：\n" + "\n".join(lines),
            {"count": len(notes)},
        )

    async def _action_search_notes(
        self, params: dict[str, Any], backend: Any, user_id: str
    ) -> ToolResult:
        query = params.get("query", "").strip()
        limit = int(params.get("limit", 10))
        if not query:
            return ToolResult.fail("query 不能为空")
        notes = await backend.search_notes(query, limit=limit)
        if not notes:
            return ToolResult.ok(f"未找到包含「{query}」的笔记。")
        lines = [f"• [{r.note_id[:8]}] {r.title}\n  {r.content[:100]}..." for r in notes]
        return ToolResult.ok(
            f"搜索「{query}」找到 {len(notes)} 条笔记：\n" + "\n".join(lines),
            {"count": len(notes)},
        )

    # ── Schema ────────────────────────────────────────────────────────────────

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(_VALID_ACTIONS),
                        "description": "笔记操作类型",
                    },
                    "title": {"type": "string", "description": "笔记标题"},
                    "content": {"type": "string", "description": "笔记内容（Markdown）"},
                    "note_id": {"type": "string", "description": "笔记 ID"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表",
                    },
                    "query": {"type": "string", "description": "搜索关键词"},
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "text"],
                        "description": "笔记格式（默认 markdown）",
                        "default": "markdown",
                    },
                    "backend": {
                        "type": "string",
                        "enum": ["local", "evernote", "baidu_netdisk"],
                        "description": "存储后端（默认 local；可指定 evernote 或 baidu_netdisk）",
                        "default": "local",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数（默认 20）",
                        "default": 20,
                    },
                },
                "required": ["action"],
            },
        }


__all__ = ["NoteTool"]

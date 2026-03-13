"""
tools/note_tool.py - Note management tool skeleton for STONE (默行者)

TODO: Phase 1b - implement full note operations.
This stub defines the interface and returns not-implemented errors.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import ToolInterface, ToolResult

logger = logging.getLogger(__name__)


class NoteTool(ToolInterface):
    """
    Manages markdown notes in the NOTES_DIR directory.

    TODO: Phase 1b - implement the following operations:
    - create_note(title, content, tags)
    - read_note(title_or_id)
    - update_note(title_or_id, content)
    - delete_note(title_or_id)          [requires confirmation]
    - list_notes(tag_filter)
    - search_notes(query)
    - tag_note(title_or_id, tags)

    Notes should be stored as markdown files under NOTES_DIR.
    Filenames: {slugified_title}_{uuid[:8]}.md
    Front matter: YAML with title, tags, created_at, updated_at.

    Integration with long-term memory: when a note is created, optionally
    add a Memory entry of category=NOTE for quick LLM recall.
    """

    name = "note_tool"
    description = (
        "管理 Markdown 笔记（创建、读取、编辑、搜索）。"
        "【Phase 1b 功能，当前不可用】"
    )
    requires_confirmation = True  # for delete operations

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        # TODO: Phase 1b - dispatch to action handlers
        return ToolResult.fail(
            "note_tool 尚未实现（Phase 1b）。"
            "计划支持：create_note、read_note、update_note、delete_note、list_notes、search_notes"
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create_note",
                            "read_note",
                            "update_note",
                            "delete_note",
                            "list_notes",
                            "search_notes",
                        ],
                        "description": "笔记操作类型",
                    },
                    "title": {"type": "string", "description": "笔记标题"},
                    "content": {"type": "string", "description": "笔记内容（Markdown）"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表",
                    },
                    "query": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["action"],
            },
        }


__all__ = ["NoteTool"]

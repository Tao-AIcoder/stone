"""
tools/memory_tool.py - Explicit memory management tool for STONE (默行者).

Handles user-initiated memory operations:
  - remember   : 显式存入记忆（"请记住..."）
  - recall      : 检索相关记忆
  - forget      : 软删除一条记忆
  - list        : 列出用户记忆
  - profile     : 生成用户画像

Auto-extraction (post-conversation hook) is handled by MemoryExtractor,
not this tool. This tool is for explicit user commands only.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tools.base import ToolInterface, ToolResult

if TYPE_CHECKING:
    from modules.memory.memory_extractor import MemoryExtractor
    from modules.memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)

_VALID_ACTIONS = ("remember", "recall", "forget", "list", "profile")


class MemoryTool(ToolInterface):
    """
    Explicit memory management for the user.

    Actions:
      remember  : save a specific piece of information permanently
      recall    : find memories related to a query
      forget    : delete a specific memory by id
      list      : list recent memories (optionally filtered by type)
      profile   : generate current user profile summary
    """

    name = "memory_tool"
    description = (
        "管理默行者的长期记忆：存入、检索、遗忘、列举记忆，或生成用户画像。"
    )
    requires_confirmation = False

    def __init__(
        self,
        memory_store: "MemoryStore",
        extractor: "MemoryExtractor",
    ) -> None:
        self._store = memory_store
        self._extractor = extractor

    def needs_confirmation_for(self, params: dict) -> bool:
        return params.get("action") == "forget"

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
        handler = getattr(self, f"_action_{action}")
        return await handler(params, user_id)

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _action_remember(
        self, params: dict[str, Any], user_id: str
    ) -> ToolResult:
        content = params.get("content", "").strip()
        memory_type = params.get("memory_type", "fact")
        if not content:
            return ToolResult.fail("content 不能为空")
        memory_id = await self._store.save(
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            source="explicit",
            initial_strength=1.0,
        )
        return ToolResult.ok(f"已记住：{content}", {"memory_id": memory_id})

    async def _action_recall(
        self, params: dict[str, Any], user_id: str
    ) -> ToolResult:
        query = params.get("query", "").strip()
        top_k = int(params.get("top_k", 8))
        if not query:
            return ToolResult.fail("query 不能为空")
        memories = await self._extractor.get_relevant_memories(user_id, query, top_k=top_k)
        if not memories:
            return ToolResult.ok("未找到相关记忆。")
        output = "\n".join(f"• {m}" for m in memories)
        return ToolResult.ok(f"找到 {len(memories)} 条相关记忆：\n{output}")

    async def _action_forget(
        self, params: dict[str, Any], user_id: str
    ) -> ToolResult:
        memory_id = params.get("memory_id", "").strip()
        if not memory_id:
            return ToolResult.fail("memory_id 不能为空")
        record = await self._store.get(memory_id)
        if not record or record.user_id != user_id:
            return ToolResult.fail(f"记忆 {memory_id[:8]} 不存在")
        # Soft delete via setting strength to 0
        import aiosqlite
        from config import settings
        db_path = str(settings.database_url).replace("sqlite:///", "")
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE long_term_memory SET active=0, strength=0 WHERE memory_id=?",
                (memory_id,),
            )
            await db.commit()
        return ToolResult.ok(f"已忘记记忆：{record.content[:60]}")

    async def _action_list(
        self, params: dict[str, Any], user_id: str
    ) -> ToolResult:
        memory_type = params.get("memory_type") or None
        limit = int(params.get("limit", 20))
        memories = await self._store.list_by_user(user_id, memory_type=memory_type, limit=limit)
        if not memories:
            return ToolResult.ok("暂无记忆。")
        lines = [
            f"[{m.memory_type}] {m.content[:80]}（强度 {m.strength:.2f}）"
            for m in memories
        ]
        return ToolResult.ok(
            f"共 {len(memories)} 条记忆：\n" + "\n".join(f"• {l}" for l in lines),
            {"count": len(memories)},
        )

    async def _action_profile(
        self, params: dict[str, Any], user_id: str
    ) -> ToolResult:
        profile = await self._extractor.generate_user_profile(user_id)
        if not profile:
            return ToolResult.ok("记忆不足，暂时无法生成用户画像。")
        return ToolResult.ok(profile)

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
                        "description": "记忆操作类型",
                    },
                    "content": {
                        "type": "string",
                        "description": "要记住的内容（action=remember 时必填）",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["entity", "preference", "fact", "behavior", "note"],
                        "description": "记忆类型（默认 fact）",
                    },
                    "query": {
                        "type": "string",
                        "description": "检索关键词（action=recall 时必填）",
                    },
                    "memory_id": {
                        "type": "string",
                        "description": "记忆ID（action=forget 时必填）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回最多几条记忆（默认 8）",
                        "default": 8,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "列表最多返回几条（默认 20）",
                        "default": 20,
                    },
                },
                "required": ["action"],
            },
        }


__all__ = ["MemoryTool"]

"""
core/context_manager.py - Conversation context management for STONE (默行者)

Maintains a sliding window of messages per conversation, compresses old
context when token usage exceeds 70% of the configured limit, and integrates
with both in-memory and SQLite memory stores.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from config import settings

if TYPE_CHECKING:
    from core.model_router import ModelRouter
    from modules.memory.inmemory_store import InMemoryStore
    from modules.memory.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Rough token budget per context window (128K tokens max for most models)
TOKEN_BUDGET = 8192
COMPRESS_THRESHOLD = 0.70   # compress when usage > 70% of budget
CHARS_PER_TOKEN = 4         # rough estimate for Chinese/English mix


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages) // CHARS_PER_TOKEN


class ContextManager:
    """
    Manages per-conversation message context with sliding window and compression.
    """

    def __init__(
        self,
        short_term: "InMemoryStore",
        long_term: "SQLiteStore",
        model_router: "ModelRouter | None" = None,
    ) -> None:
        self.short_term = short_term
        self.long_term = long_term
        self.model_router = model_router
        self.window_size: int = settings.context_window

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_context(
        self, user_id: str, conv_id: str
    ) -> list[dict[str, Any]]:
        """
        Return the current message window for this conversation (excluding
        the system prompt).  If a summary exists it is prepended as a
        system-level context message.
        """
        messages = await self.short_term.get_context(user_id, conv_id) or []

        # If no in-memory context, try to restore from SQLite
        if not messages:
            db_messages = await self.long_term.get_conversation_messages(
                conv_id=conv_id, limit=self.window_size
            )
            messages = [
                {"role": m.role.value, "content": m.content}
                for m in db_messages
            ]
            if messages:
                await self.short_term.save_context(user_id, conv_id, messages)

        # Prepend summary if available
        summary = await self.short_term.get_summary(user_id, conv_id)
        if not summary:
            summary = await self.long_term.get_conversation_summary(conv_id)

        result: list[dict[str, Any]] = []
        if summary:
            result.append({
                "role": "system",
                "content": f"[之前对话摘要]\n{summary}",
            })
        result.extend(messages[-self.window_size:])
        return result

    async def save_context(
        self,
        user_id: str,
        conv_id: str,
        user_msg: str,
        assistant_msg: str,
    ) -> None:
        """Append a new exchange and compress if needed."""
        messages = await self.short_term.get_context(user_id, conv_id) or []

        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": assistant_msg})

        # Trim to sliding window
        if len(messages) > self.window_size * 2:
            messages = messages[-(self.window_size * 2):]

        # Check if compression is needed
        token_count = _estimate_tokens(messages)
        if token_count > TOKEN_BUDGET * COMPRESS_THRESHOLD:
            messages = await self._compress(user_id, conv_id, messages)

        await self.short_term.save_context(user_id, conv_id, messages)

        # Persist to SQLite
        try:
            from models.conversation import Message, MessageRole
            await self.long_term.save_message(
                Message(
                    conv_id=conv_id,
                    user_id=user_id,
                    role=MessageRole.USER,
                    content=user_msg,
                    token_count=len(user_msg) // CHARS_PER_TOKEN,
                )
            )
            await self.long_term.save_message(
                Message(
                    conv_id=conv_id,
                    user_id=user_id,
                    role=MessageRole.ASSISTANT,
                    content=assistant_msg,
                    token_count=len(assistant_msg) // CHARS_PER_TOKEN,
                )
            )
        except Exception as exc:
            logger.warning("Failed to persist messages to SQLite: %s", exc)

    # ── Compression ───────────────────────────────────────────────────────────

    async def _compress(
        self,
        user_id: str,
        conv_id: str,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Summarize the older half of the message list and replace it with
        a summary node, keeping the most recent messages verbatim.
        """
        half = len(messages) // 2
        old_messages = messages[:half]
        recent_messages = messages[half:]

        logger.info(
            "Compressing context [conv=%s]: %d messages -> summary + %d",
            conv_id,
            len(old_messages),
            len(recent_messages),
        )

        summary = await self._generate_summary(old_messages, user_id)
        if summary:
            await self.short_term.save_summary(user_id, conv_id, summary)
            try:
                await self.long_term.update_conversation_summary(conv_id, summary)
            except Exception as exc:
                logger.warning("Failed to persist summary to SQLite: %s", exc)

        return recent_messages

    async def _generate_summary(
        self, messages: list[dict[str, Any]], user_id: str
    ) -> str:
        if self.model_router is None:
            return ""

        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个对话摘要助手。请将以下对话历史压缩成简洁的摘要，"
                    "保留关键信息、决策和上下文，用中文回答，不超过300字。"
                ),
            },
            *messages,
            {"role": "user", "content": "请生成以上对话的简洁摘要。"},
        ]

        try:
            llm_resp = await self.model_router.chat(
                messages=summary_prompt,
                task_type="analysis",
                user_id=user_id,
                privacy_sensitive=True,  # summaries may contain private data -> local
            )
            return llm_resp.text.strip()
        except Exception as exc:
            logger.warning("Summary generation failed: %s", exc)
            return ""


__all__ = ["ContextManager"]

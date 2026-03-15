"""
modules/memory/memory_extractor.py - LLM-based memory extraction for STONE.

After each conversation turn, extracts:
  - entities    (人名、地点、项目、产品…)
  - preferences (用户偏好、习惯、口味…)
  - facts       (用户告知的事实性信息)
  - behaviors   (AI 行为模式，用于强化学习)

All extraction uses LocalModelManager (privacy_sensitive=True → Ollama only).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from modules.memory.local_model_manager import LocalModelManager
    from modules.memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)

# Positive feedback keywords that trigger reinforcement of last AI behavior
_PRAISE_WORDS = {
    "好", "很好", "不错", "棒", "厉害", "对", "就这样", "继续",
    "太好了", "完美", "正确", "赞", "喜欢", "满意", "就是这个",
    "good", "great", "perfect", "exactly", "yes", "correct", "nice",
}

_EXPLICIT_REMEMBER_PATTERNS = [
    r"请记住(.+)",
    r"记住(.+)",
    r"帮我记(.+)",
    r"记一下(.+)",
    r"remember[：:]\s*(.+)",
    r"note[：:]\s*(.+)",
]

_EXTRACT_PROMPT = """\
请从以下对话中提取有价值的长期记忆信息，只返回 JSON，不要解释。

对话内容：
{conversation}

请提取以下类型的信息（如果存在）：
- entities: 人名、地点、项目名、产品名等实体（数组，每项为字符串）
- preferences: 用户偏好、习惯、口味（数组，每项为字符串）
- facts: 用户告知的事实性信息（数组，每项为字符串）
- behaviors: AI 的哪些行为/回答方式令用户满意（数组，每项为字符串）

返回格式：
{{
  "entities": [],
  "preferences": [],
  "facts": [],
  "behaviors": []
}}

如果某类别没有信息，返回空数组。只返回 JSON，不要其他内容。"""

_COMPRESS_PROMPT = """\
请将以下记忆内容压缩为简洁摘要，保留核心信息，去掉细节，不超过 50 字，只返回压缩后的文本：

{content}"""

_PROFILE_PROMPT = """\
根据以下用户记忆信息，生成一份简洁的用户画像，不超过 300 字，用中文，突出用户的主要特征、偏好和习惯：

{memories}"""


class MemoryExtractor:
    """
    Extracts and manages memories from conversation turns.

    Usage (in agent.py post-conversation hook):
        await extractor.extract_from_turn(
            user_id=user_id,
            user_text=user_message,
            assistant_text=assistant_response,
        )

    For reinforcement (user praise):
        await extractor.handle_reinforcement(user_id, last_behavior_memory_id)

    For explicit memory commands:
        await extractor.handle_explicit(user_id, text)
    """

    def __init__(
        self,
        local_model: "LocalModelManager",
        memory_store: "MemoryStore",
    ) -> None:
        self._local_model = local_model
        self._store = memory_store

    # ── Main Extraction ───────────────────────────────────────────────────────

    async def extract_from_turn(
        self,
        user_id: str,
        user_text: str,
        assistant_text: str,
        conv_id: str = "",
    ) -> dict[str, list[str]]:
        """
        Run extraction on a completed conversation turn.
        Returns dict of {type: [content, ...]} for logging.
        """
        # Check for explicit "请记住" first
        explicit = self._detect_explicit(user_text)
        if explicit:
            await self._store.save(
                user_id=user_id,
                memory_type="fact",
                content=explicit,
                source="explicit",
                initial_strength=1.0,
            )
            logger.info("Explicit memory saved for user %s: %r", user_id[:12], explicit[:60])
            return {"facts": [explicit]}

        # Auto extraction via LLM
        conversation = f"用户: {user_text}\n默行者: {assistant_text}"
        prompt = _EXTRACT_PROMPT.format(conversation=conversation)
        try:
            raw = await self._local_model.extract(prompt, user_id=user_id)
            extracted = self._parse_json(raw)
        except Exception as exc:
            logger.warning("Memory extraction failed: %s", exc)
            return {}

        saved: dict[str, list[str]] = {}
        for memory_type, items in extracted.items():
            if not isinstance(items, list):
                continue
            saved[memory_type] = []
            for item in items:
                if isinstance(item, str) and item.strip():
                    await self._store.save(
                        user_id=user_id,
                        memory_type=memory_type,
                        content=item.strip(),
                        source="auto_extract",
                    )
                    saved[memory_type].append(item.strip())

        if any(saved.values()):
            logger.debug("Extracted memories for %s: %s", user_id[:12], {k: len(v) for k, v in saved.items()})
        return saved

    # ── Explicit Memory ───────────────────────────────────────────────────────

    def _detect_explicit(self, text: str) -> str:
        """Return the content to remember if text contains explicit memory command."""
        for pattern in _EXPLICIT_REMEMBER_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()
        return ""

    async def handle_explicit(self, user_id: str, text: str) -> str | None:
        """
        If text contains 'please remember', save it and return confirmation.
        Returns None if text is not an explicit memory command.
        """
        content = self._detect_explicit(text)
        if not content:
            return None
        memory_id = await self._store.save(
            user_id=user_id,
            memory_type="fact",
            content=content,
            source="explicit",
            initial_strength=1.0,
        )
        return f"已记住：{content}"

    # ── Reinforcement ─────────────────────────────────────────────────────────

    def is_praise(self, text: str) -> bool:
        """Return True if the text is a positive reinforcement signal.
        Single-char words only match exactly; multi-char words allow substring match
        to avoid false positives (e.g. '不对' containing '对')."""
        stripped = text.strip()
        if stripped in _PRAISE_WORDS:
            return True
        # Only substring-match words with len >= 2 to avoid single-char ambiguity
        return any(w in text for w in _PRAISE_WORDS if len(w) >= 2)

    async def reinforce_last_behavior(
        self,
        user_id: str,
        last_behavior_memory_id: str | None,
    ) -> None:
        """
        User praised the AI. Reinforce the last behavior memory.
        If no behavior memory id is provided, find the most recent behavior memory.
        """
        if last_behavior_memory_id:
            await self._store.reinforce(last_behavior_memory_id)
            return

        # Find most recent behavior memory
        behaviors = await self._store.list_by_user(
            user_id, memory_type="behavior", limit=1
        )
        if behaviors:
            await self._store.reinforce(behaviors[0].memory_id)
            logger.debug("Reinforced behavior memory %s", behaviors[0].memory_id[:8])

    # ── Compression ───────────────────────────────────────────────────────────

    async def compress_memory(self, memory_id: str, content: str) -> str:
        """Generate compressed version of a memory content."""
        prompt = _COMPRESS_PROMPT.format(content=content)
        try:
            compressed = await self._local_model.extract(prompt)
            compressed = compressed.strip().strip('"')
            await self._store.update_compressed(memory_id, compressed)
            return compressed
        except Exception as exc:
            logger.warning("Memory compression failed: %s", exc)
            return content[:100] + "…"

    # ── Weekly Profile ────────────────────────────────────────────────────────

    async def generate_user_profile(self, user_id: str) -> str:
        """
        Generate a weekly user profile summary from all active memories.
        Called by the weekly scheduled job.
        """
        memories = await self._store.list_by_user(user_id, limit=200)
        if not memories:
            return ""

        memory_text = "\n".join(
            f"[{m.memory_type}] {m.content}" for m in memories
        )
        prompt = _PROFILE_PROMPT.format(memories=memory_text)
        try:
            profile = await self._local_model.extract(prompt, user_id=user_id)
            return profile.strip()
        except Exception as exc:
            logger.warning("Profile generation failed: %s", exc)
            return ""

    # ── Context Injection ─────────────────────────────────────────────────────

    async def get_relevant_memories(
        self,
        user_id: str,
        query: str,
        top_k: int = 8,
    ) -> list[str]:
        """
        Retrieve memories most relevant to current query for context injection.
        Uses semantic ranking if embeddings available, else keyword search.
        """
        all_memories = await self._store.list_by_user(user_id, limit=200)
        if not all_memories:
            return []

        # Try semantic ranking
        try:
            candidates = [
                {"memory_id": m.memory_id, "content": m.content, "memory_type": m.memory_type}
                for m in all_memories
            ]
            ranked = self._local_model.rank_by_similarity(query, candidates, top_k=top_k)
            result = [f"[{r['memory_type']}] {r['content']}" for r in ranked]
            # Touch accessed memories
            for r in ranked:
                await self._store.touch(r["memory_id"])
            return result
        except Exception:
            # Fallback: keyword search
            keyword_results = await self._store.search_keyword(user_id, query, limit=top_k)
            return [f"[{m.memory_type}] {m.content}" for m in keyword_results]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from LLM response (may have markdown fencing)."""
        # Strip markdown code fences
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        text = text.rstrip("```").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in text
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                return json.loads(m.group(0))
            return {}


__all__ = ["MemoryExtractor"]

"""
tests/test_memory_extractor.py - 记忆提取器单元测试

覆盖：
  - 显式记忆检测（"请记住…"等关键词）
  - 夸奖检测
  - JSON 解析（含 Markdown 代码块）
  - 用户画像生成（mock LLM）
  - is_praise 覆盖多种表达
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.memory.memory_extractor import MemoryExtractor


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_extractor(mock_extract_return: str = "{}"):
    local_model = MagicMock()
    local_model.extract = AsyncMock(return_value=mock_extract_return)
    local_model.rank_by_similarity = MagicMock(return_value=[])

    store = MagicMock()
    store.save = AsyncMock(return_value="mock-memory-id")
    store.list_by_user = AsyncMock(return_value=[])
    store.search_keyword = AsyncMock(return_value=[])
    store.touch = AsyncMock()
    store.reinforce = AsyncMock()
    store.update_compressed = AsyncMock()

    extractor = MemoryExtractor(local_model=local_model, memory_store=store)
    return extractor, local_model, store


# ── Explicit Memory Detection ─────────────────────────────────────────────────

class TestExplicitMemoryDetection:
    def test_detect_qing_jizhu(self):
        extractor, _, _ = _make_extractor()
        result = extractor._detect_explicit("请记住我不喜欢废话")
        assert result == "我不喜欢废话"

    def test_detect_jizhu(self):
        extractor, _, _ = _make_extractor()
        result = extractor._detect_explicit("记住这个号码：13800138000")
        assert "13800138000" in result

    def test_detect_bangwo_ji(self):
        extractor, _, _ = _make_extractor()
        result = extractor._detect_explicit("帮我记一下今天开会结论")
        assert "今天开会结论" in result

    def test_no_match_returns_empty(self):
        extractor, _, _ = _make_extractor()
        result = extractor._detect_explicit("今天天气不错")
        assert result == ""

    def test_english_remember(self):
        extractor, _, _ = _make_extractor()
        result = extractor._detect_explicit("remember: always use markdown")
        assert "always use markdown" in result.lower()

    @pytest.mark.asyncio
    async def test_explicit_command_saves_fact(self):
        extractor, _, store = _make_extractor()
        confirmation = await extractor.handle_explicit("u1", "请记住我喜欢简洁回答")
        assert confirmation is not None
        assert "简洁" in confirmation
        store.save.assert_called_once()
        call_kwargs = store.save.call_args[1]
        assert call_kwargs["source"] == "explicit"
        assert call_kwargs["initial_strength"] == 1.0

    @pytest.mark.asyncio
    async def test_non_explicit_returns_none(self):
        extractor, _, _ = _make_extractor()
        result = await extractor.handle_explicit("u1", "今天天气不错")
        assert result is None


# ── Praise Detection ──────────────────────────────────────────────────────────

class TestPraiseDetection:
    @pytest.mark.parametrize("text", [
        "好", "很好", "不错", "棒", "就这样", "太好了", "完美",
        "good", "great", "perfect", "yes", "correct",
    ])
    def test_praise_words(self, text):
        extractor, _, _ = _make_extractor()
        assert extractor.is_praise(text), f"{text!r} should be praise"

    @pytest.mark.parametrize("text", [
        "不对", "错了", "重新来", "你理解错了", "这不是我要的",
    ])
    def test_non_praise_words(self, text):
        extractor, _, _ = _make_extractor()
        assert not extractor.is_praise(text), f"{text!r} should NOT be praise"


# ── JSON Parsing ──────────────────────────────────────────────────────────────

class TestJsonParsing:
    def test_plain_json(self):
        extractor, _, _ = _make_extractor()
        result = extractor._parse_json('{"entities": ["张三"], "preferences": []}')
        assert result["entities"] == ["张三"]

    def test_markdown_fenced_json(self):
        extractor, _, _ = _make_extractor()
        text = '```json\n{"facts": ["用户是工程师"]}\n```'
        result = extractor._parse_json(text)
        assert result["facts"] == ["用户是工程师"]

    def test_json_embedded_in_text(self):
        extractor, _, _ = _make_extractor()
        text = '以下是提取结果：\n{"preferences": ["简洁"]}\n就这些。'
        result = extractor._parse_json(text)
        assert result["preferences"] == ["简洁"]

    def test_invalid_json_returns_empty(self):
        extractor, _, _ = _make_extractor()
        result = extractor._parse_json("这不是JSON")
        assert result == {}


# ── Auto Extraction ───────────────────────────────────────────────────────────

class TestAutoExtraction:
    @pytest.mark.asyncio
    async def test_extracts_and_saves_preferences(self):
        mock_resp = json.dumps({
            "entities": [],
            "preferences": ["用户喜欢简洁回答"],
            "facts": [],
            "behaviors": [],
        })
        extractor, local_model, store = _make_extractor(mock_resp)
        result = await extractor.extract_from_turn(
            user_id="u1",
            user_text="简洁一点",
            assistant_text="好的，我会简洁。",
        )
        assert "preferences" in result
        assert len(result["preferences"]) == 1
        store.save.assert_called()

    @pytest.mark.asyncio
    async def test_explicit_command_bypasses_llm(self):
        """显式记忆命令不应调用 LLM 提取。"""
        extractor, local_model, store = _make_extractor()
        await extractor.extract_from_turn(
            user_id="u1",
            user_text="请记住我叫王松涛",
            assistant_text="好的，已记住。",
        )
        local_model.extract.assert_not_called()
        store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_reinforcement_calls_reinforce(self):
        extractor, _, store = _make_extractor()
        # Mock behavior memory
        from unittest.mock import MagicMock
        mock_memory = MagicMock()
        mock_memory.memory_id = "behavior-001"
        store.list_by_user = AsyncMock(return_value=[mock_memory])

        await extractor.reinforce_last_behavior("u1", None)
        store.reinforce.assert_called_once_with("behavior-001")


# ── Profile Generation ────────────────────────────────────────────────────────

class TestProfileGeneration:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_memories(self):
        extractor, _, store = _make_extractor()
        store.list_by_user = AsyncMock(return_value=[])
        profile = await extractor.generate_user_profile("u1")
        assert profile == ""

    @pytest.mark.asyncio
    async def test_generates_profile_with_memories(self):
        extractor, local_model, store = _make_extractor()
        from unittest.mock import MagicMock
        mock_mem = MagicMock()
        mock_mem.memory_type = "preference"
        mock_mem.content = "喜欢简洁"
        store.list_by_user = AsyncMock(return_value=[mock_mem])
        local_model.extract = AsyncMock(return_value="用户偏好简洁高效的交互方式。")

        profile = await extractor.generate_user_profile("u1")
        assert profile != ""
        local_model.extract.assert_called_once()

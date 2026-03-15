"""
tests/test_local_model_manager.py - LocalModelManager 单元测试

覆盖：
  - 正确构建 sentence_transformers 后端（mock，不实际加载模型）
  - 正确构建 ollama 后端
  - embed / similarity / rank_by_similarity 接口调用
  - extract 强制 privacy_sensitive=True
  - 未知 driver 抛出 ValueError
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_model_router(text="{}"):
    router = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = text
    router.chat = AsyncMock(return_value=mock_resp)
    return router


def _make_manager(driver="sentence_transformers"):
    from modules.memory.local_model_manager import LocalModelManager
    router = _make_model_router()
    with patch(
        "modules.memory.embedding_backends.sentence_transformers_backend"
        ".SentenceTransformersBackend._load",
        return_value=MagicMock(
            encode=MagicMock(return_value=MagicMock(tolist=lambda: [0.1, 0.2, 0.3]))
        ),
    ):
        mgr = LocalModelManager(
            model_router=router,
            embedding_config={"driver": driver, "model": "BAAI/bge-small-zh-v1.5"},
        )
    return mgr, router


# ── Construction ──────────────────────────────────────────────────────────────

class TestConstruction:
    def test_default_sentence_transformers(self):
        from modules.memory.local_model_manager import LocalModelManager
        from modules.memory.embedding_backends.sentence_transformers_backend import (
            SentenceTransformersBackend,
        )
        router = _make_model_router()
        mgr = LocalModelManager(router)
        assert isinstance(mgr._embedding, SentenceTransformersBackend)

    def test_ollama_backend_selected(self):
        from modules.memory.local_model_manager import LocalModelManager
        from modules.memory.embedding_backends.ollama_backend import OllamaEmbeddingBackend
        router = _make_model_router()
        mgr = LocalModelManager(
            router,
            embedding_config={"driver": "ollama", "model": "nomic-embed-text"},
        )
        assert isinstance(mgr._embedding, OllamaEmbeddingBackend)

    def test_unknown_driver_raises(self):
        from modules.memory.local_model_manager import _build_embedding_backend
        with pytest.raises(ValueError, match="Unknown embedding driver"):
            _build_embedding_backend({"driver": "nonexistent"})


# ── SentenceTransformers Backend ──────────────────────────────────────────────

class TestSentenceTransformersBackend:
    def test_similarity_unit_vectors(self):
        from modules.memory.embedding_backends.sentence_transformers_backend import (
            SentenceTransformersBackend,
        )
        backend = SentenceTransformersBackend()
        # Identical vectors → similarity = 1.0
        v = [0.6, 0.8]
        assert backend.similarity(v, v) == pytest.approx(1.0, abs=0.001)

    def test_similarity_orthogonal(self):
        from modules.memory.embedding_backends.sentence_transformers_backend import (
            SentenceTransformersBackend,
        )
        backend = SentenceTransformersBackend()
        # Orthogonal vectors → similarity ≈ 0
        assert backend.similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=0.001)

    def test_similarity_empty_returns_zero(self):
        from modules.memory.embedding_backends.sentence_transformers_backend import (
            SentenceTransformersBackend,
        )
        backend = SentenceTransformersBackend()
        assert backend.similarity([], []) == 0.0

    def test_missing_library_raises_runtime(self):
        """If sentence-transformers not installed, helpful error is raised."""
        from modules.memory.embedding_backends.sentence_transformers_backend import (
            SentenceTransformersBackend,
        )
        backend = SentenceTransformersBackend()
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises((RuntimeError, ImportError)):
                backend.embed("test")


# ── rank_by_similarity ────────────────────────────────────────────────────────

class TestRankBySimilarity:
    def test_returns_top_k(self):
        from modules.memory.embedding_backends.sentence_transformers_backend import (
            SentenceTransformersBackend,
        )
        backend = SentenceTransformersBackend()
        # Mock embed to return deterministic vectors
        call_count = 0
        vectors = [
            [1.0, 0.0],   # query
            [0.9, 0.1],   # candidate 0 (high similarity)
            [0.5, 0.5],   # candidate 1 (medium)
            [0.0, 1.0],   # candidate 2 (low similarity)
        ]
        def mock_embed(text):
            nonlocal call_count
            v = vectors[min(call_count, len(vectors) - 1)]
            call_count += 1
            return v

        backend.embed = mock_embed
        candidates = [
            {"id": "a", "content": "高相似"},
            {"id": "b", "content": "中相似"},
            {"id": "c", "content": "低相似"},
        ]
        ranked = backend.rank_by_similarity("query", candidates, top_k=2)
        assert len(ranked) == 2
        assert ranked[0]["id"] == "a"  # highest similarity first

    def test_empty_candidates(self):
        from modules.memory.embedding_backends.sentence_transformers_backend import (
            SentenceTransformersBackend,
        )
        backend = SentenceTransformersBackend()
        result = backend.rank_by_similarity("query", [])
        assert result == []


# ── Extract (privacy enforcement) ────────────────────────────────────────────

class TestExtractPrivacy:
    @pytest.mark.asyncio
    async def test_extract_uses_privacy_sensitive_true(self):
        """extract() must call ModelRouter with privacy_sensitive=True."""
        from modules.memory.local_model_manager import LocalModelManager
        router = _make_model_router(text='{"result": "ok"}')
        mgr = LocalModelManager(router)
        await mgr.extract("test prompt", user_id="u1")

        call_kwargs = router.chat.call_args[1]
        assert call_kwargs.get("privacy_sensitive") is True, (
            "extract() must enforce privacy_sensitive=True to route to local Ollama"
        )

    @pytest.mark.asyncio
    async def test_extract_returns_llm_text(self):
        from modules.memory.local_model_manager import LocalModelManager
        router = _make_model_router(text="extracted content")
        mgr = LocalModelManager(router)
        result = await mgr.extract("prompt")
        assert result == "extracted content"

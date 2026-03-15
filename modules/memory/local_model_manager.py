"""
modules/memory/local_model_manager.py - Local model manager for STONE (默行者)

Manages local (privacy-safe) model backends used for:
  - Memory extraction (entities, preferences, facts) via Ollama
  - Semantic similarity / retrieval via embedded EmbeddingInterface

Both Phase 1b memory and Phase 3 RAG share this manager.
All operations stay on-device: no data sent to cloud APIs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from config import settings

if TYPE_CHECKING:
    from core.model_router import ModelRouter
    from modules.interfaces.embedding import EmbeddingInterface

logger = logging.getLogger(__name__)


def _build_embedding_backend(cfg: dict[str, Any]) -> "EmbeddingInterface":
    """Instantiate the configured embedding backend."""
    driver = cfg.get("driver", "sentence_transformers")
    model = cfg.get("model", "BAAI/bge-small-zh-v1.5")

    if driver == "sentence_transformers":
        from modules.memory.embedding_backends.sentence_transformers_backend import (
            SentenceTransformersBackend,
        )
        return SentenceTransformersBackend(model_name=model)

    if driver == "ollama":
        from modules.memory.embedding_backends.ollama_backend import OllamaEmbeddingBackend
        base_url = cfg.get("base_url", "http://localhost:11434")
        return OllamaEmbeddingBackend(model=model, base_url=base_url)

    raise ValueError(f"Unknown embedding driver: {driver!r}")


class LocalModelManager:
    """
    Provides two local model capabilities:

    1. embedding  — semantic vector operations (always local)
    2. extraction — LLM-based entity/preference/fact extraction
                    (routes through ModelRouter with privacy_sensitive=True
                     to guarantee Ollama is used)

    Singleton-like: constructed once in main.py and shared via app.state.
    """

    def __init__(
        self,
        model_router: "ModelRouter",
        embedding_config: dict[str, Any] | None = None,
        extraction_model: str = "qwen2.5:14b",
    ) -> None:
        self._model_router = model_router
        self._extraction_model = extraction_model

        emb_cfg = embedding_config or {
            "driver": "sentence_transformers",
            "model": "BAAI/bge-small-zh-v1.5",
        }
        self._embedding: "EmbeddingInterface" = _build_embedding_backend(emb_cfg)
        logger.info(
            "LocalModelManager init: embedding=%s/%s  extraction=%s",
            emb_cfg.get("driver"),
            emb_cfg.get("model"),
            extraction_model,
        )

    # ── Embedding API ─────────────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        return self._embedding.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._embedding.embed_batch(texts)

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        return self._embedding.similarity(vec_a, vec_b)

    def rank_by_similarity(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        text_key: str = "content",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return self._embedding.rank_by_similarity(query, candidates, text_key, top_k)

    # ── Extraction API ────────────────────────────────────────────────────────

    async def extract(self, prompt: str, user_id: str = "system") -> str:
        """
        Run a prompt through the local extraction model.
        Always uses privacy_sensitive=True → routes to Ollama.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个信息提取助手，只返回 JSON，不解释，不废话。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        resp = await self._model_router.chat(
            messages=messages,
            task_type="analysis",
            user_id=user_id,
            privacy_sensitive=True,   # ← 强制本地模型
        )
        return resp.text.strip()


__all__ = ["LocalModelManager"]

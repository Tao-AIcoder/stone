"""
modules/interfaces/embedding.py - Embedding backend ABC for STONE (默行者)

All local embedding implementations must implement EmbeddingInterface.
Embeddings are used for semantic memory retrieval and (Phase 3) RAG.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EmbeddingInterface(ABC):
    """
    Abstract interface for local embedding models.

    Implementations:
      - SentenceTransformersBackend  (default, embedded, no Ollama needed)
      - OllamaEmbeddingBackend       (optional, via Ollama API)

    All embedding operations are privacy-safe: no data leaves the host.
    """

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return embedding vector for a single text string."""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a list of texts."""
        ...

    @abstractmethod
    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Return cosine similarity between two vectors (0.0 ~ 1.0)."""
        ...

    def rank_by_similarity(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        text_key: str = "content",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Rank candidate dicts by semantic similarity to query.
        Each candidate must have a field named text_key.
        Returns top_k candidates sorted by descending similarity.
        """
        if not candidates:
            return []
        query_vec = self.embed(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in candidates:
            text = item.get(text_key, "")
            if not text:
                continue
            vec = self.embed(str(text))
            score = self.similarity(query_vec, vec)
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]


__all__ = ["EmbeddingInterface"]

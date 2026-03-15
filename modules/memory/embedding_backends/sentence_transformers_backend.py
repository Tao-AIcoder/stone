"""
modules/memory/embedding_backends/sentence_transformers_backend.py

Default embedded embedding backend using sentence-transformers.
No Ollama required. Model is downloaded once (~24MB) and cached locally.

Default model: BAAI/bge-small-zh-v1.5
  - Chinese-optimised
  - 24 MB, CPU-friendly
  - 512-dim vectors
"""

from __future__ import annotations

import logging
import math
from typing import Any

from modules.interfaces.embedding import EmbeddingInterface

logger = logging.getLogger(__name__)


class SentenceTransformersBackend(EmbeddingInterface):
    """
    Embedding backend using sentence-transformers (fully local, no API calls).

    Lazy-loads the model on first use to avoid slowing down startup.
    Thread-safe: the underlying model uses internal locking.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        self._model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import]
                logger.info("Loading embedding model: %s", self._model_name)
                self._model = SentenceTransformer(self._model_name)
                logger.info("Embedding model loaded OK")
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers 未安装。请执行: pip install sentence-transformers"
                ) from exc
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vecs]

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Cosine similarity for pre-normalised vectors = dot product."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        # Clamp to [-1, 1] due to floating point noise
        return max(-1.0, min(1.0, dot))


__all__ = ["SentenceTransformersBackend"]

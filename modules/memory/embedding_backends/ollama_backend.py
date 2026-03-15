"""
modules/memory/embedding_backends/ollama_backend.py

Optional embedding backend using Ollama's embedding API.
Use this if you prefer to keep all model inference in Ollama
(e.g. nomic-embed-text, mxbai-embed-large).

Requires Ollama to be running and the chosen model to be pulled.
"""

from __future__ import annotations

import logging
import math

import httpx

from modules.interfaces.embedding import EmbeddingInterface

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "nomic-embed-text"
_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaEmbeddingBackend(EmbeddingInterface):
    """
    Embedding backend that delegates to Ollama's /api/embeddings endpoint.

    Config example (stone.config.json):
        "local_model": {
            "embedding": {
                "driver": "ollama",
                "model": "nomic-embed-text",
                "base_url": "http://localhost:11434"
            }
        }
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    def _call(self, text: str) -> list[float]:
        url = f"{self._base_url}/api/embeddings"
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json={"model": self._model, "prompt": text})
            resp.raise_for_status()
            data = resp.json()
            return data["embedding"]

    def embed(self, text: str) -> list[float]:
        return self._call(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._call(t) for t in texts]

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


__all__ = ["OllamaEmbeddingBackend"]

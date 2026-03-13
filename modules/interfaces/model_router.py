"""
modules/interfaces/model_router.py - Model router interface.

Built-in drivers:
  direct → core.model_router.ModelRouter  (Phase 1, default)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ModelRouterInterface(ABC):
    """
    Contract for LLM routing and inference.

    Routes requests to appropriate models (local Ollama, cloud APIs)
    based on task type and privacy sensitivity.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        task_type: str = "general",
        user_id: str = "default_user",
        privacy_sensitive: bool = False,
    ) -> str:
        """
        Send messages to an appropriate model and return the response text.

        Args:
            messages:          Conversation history in OpenAI format.
            task_type:         Hint for model selection (e.g. "code", "chat").
            user_id:           User making the request (for audit / routing).
            privacy_sensitive: If True, force local model regardless of config.

        Returns:
            Model response as plain text.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release HTTP sessions and connections."""
        ...


__all__ = ["ModelRouterInterface"]

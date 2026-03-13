"""
modules/interfaces/prompt_guard.py - Prompt injection detection interface.

Built-in drivers:
  regex → security.prompt_guard.PromptGuard  (Phase 1, default)
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PromptGuardInterface(ABC):
    """
    Contract for detecting and handling prompt injection attempts.
    """

    @abstractmethod
    def scan(self, content: str) -> None:
        """
        Scan content for prompt injection patterns.

        Raises PromptInjectionError on a high-severity match.
        Returns None if content is safe.
        """
        ...

    @abstractmethod
    def scan_safe(self, content: str) -> tuple[bool, str]:
        """
        Non-raising variant of scan().

        Returns:
            (is_safe, pattern_name) — is_safe=True means no injection found;
            pattern_name is "" when safe, or the matched pattern name when not.
        """
        ...

    @abstractmethod
    def wrap_untrusted(self, content: str, source: str = "external") -> str:
        """
        Wrap potentially untrusted content in boundary markers so the LLM
        can distinguish it from system instructions.

        Args:
            content: Raw untrusted text (e.g. web search result, file content).
            source:  Label identifying the origin (for logging/display).

        Returns:
            Wrapped string with clear start/end markers.
        """
        ...


__all__ = ["PromptGuardInterface"]

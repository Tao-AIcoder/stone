"""
security/prompt_guard.py - Prompt injection detection for STONE (默行者)

Scans user and external content for instruction injection attempts and
wraps untrusted content in a safe boundary marker.
"""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

from models.errors import PromptInjectionError

logger = logging.getLogger(__name__)

UNTRUSTED_WRAPPER = (
    "--- UNTRUSTED CONTENT BEGIN (source: {source}) ---\n"
    "{content}\n"
    "--- UNTRUSTED CONTENT END ---"
)


class InjectionPattern(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    severity: str  # "high" | "medium"


# Known injection / jailbreak patterns
_PATTERNS: list[InjectionPattern] = [
    # Role override
    InjectionPattern(
        "role_override_ignore",
        re.compile(
            r"ignore\s+(previous|all|above|prior)(\s+\w+)?\s*(instructions?|rules?|prompts?|guidelines?)",
            re.IGNORECASE,
        ),
        "high",
    ),
    InjectionPattern(
        "role_override_forget",
        re.compile(
            r"forget\s+(everything|all|your\s+(rules?|instructions?|training))",
            re.IGNORECASE,
        ),
        "high",
    ),
    InjectionPattern(
        "role_override_disregard",
        re.compile(
            r"disregard\s+(your\s+)?(previous|prior|original)?\s*(instructions?|rules?|constraints?|system\s+prompt)",
            re.IGNORECASE,
        ),
        "high",
    ),
    # Persona hijack
    InjectionPattern(
        "persona_hijack_pretend",
        re.compile(
            r"(pretend|act|behave|roleplay)\s+(you\s+are|as\s+if\s+you\s+are|as)\s+(a\s+)?(jailbroken|evil|unrestricted|uncensored|DAN|god|admin)",
            re.IGNORECASE,
        ),
        "high",
    ),
    InjectionPattern(
        "dan_jailbreak",
        re.compile(r"\bDAN\b.*\bdo\s+anything\s+now\b", re.IGNORECASE),
        "high",
    ),
    # System prompt extraction
    InjectionPattern(
        "system_prompt_extraction",
        re.compile(
            r"(print|reveal|show|output|tell\s+me|repeat)\s+(your\s+)?(system\s+prompt|initial\s+prompt|original\s+instructions?|secret\s+instructions?)",
            re.IGNORECASE,
        ),
        "medium",
    ),
    # Instruction injection via formatting tricks
    InjectionPattern(
        "markdown_injection",
        re.compile(
            r"```\s*(system|instructions?|prompt)\s*\n",
            re.IGNORECASE | re.MULTILINE,
        ),
        "medium",
    ),
    # Override safety
    InjectionPattern(
        "safety_override",
        re.compile(
            r"(bypass|override|disable|turn\s+off)\s+(your\s+)?(\w+\s+)?(safety|content\s+filter|restrictions?|guardrails?|limits?)",
            re.IGNORECASE,
        ),
        "high",
    ),
    # Chinese-language patterns
    InjectionPattern(
        "cn_role_override",
        re.compile(
            r"(忽略|无视|取消).{0,15}(指令|规则|限制|设定|提示)",
            re.IGNORECASE,
        ),
        "high",
    ),
    InjectionPattern(
        "cn_persona_hijack",
        re.compile(
            r"(假装|扮演|模拟)\s*你是\s*(不受限制|越狱|邪恶|无道德|DAN)",
            re.IGNORECASE,
        ),
        "high",
    ),
]


class PromptGuard:
    """
    Scans content for prompt injection patterns and wraps untrusted content
    with boundary markers to prevent instruction leakage.
    """

    def __init__(self, strict: bool = False) -> None:
        """
        Args:
            strict: If True, raise on medium-severity patterns too.
                    Default False (only raise on high-severity).
        """
        self.strict = strict

    def scan(self, content: str) -> bool:
        """
        Scan content for injection patterns.

        Returns:
            True if content is considered safe.
        Raises:
            PromptInjectionError: if an injection pattern is detected.
        """
        for pat in _PATTERNS:
            if self.strict or pat.severity == "high":
                if pat.pattern.search(content):
                    logger.warning(
                        "PromptGuard: injection pattern detected: %s",
                        pat.name,
                    )
                    raise PromptInjectionError(
                        message=f"检测到提示词注入模式：{pat.name}",
                        pattern=pat.name,
                    )
            else:
                # medium: log but don't block (unless strict)
                if pat.pattern.search(content):
                    logger.info(
                        "PromptGuard: suspicious pattern (medium) detected: %s",
                        pat.name,
                    )
        return True

    def scan_safe(self, content: str) -> tuple[bool, str]:
        """
        Scan without raising. Returns (is_safe, pattern_name_or_empty).
        """
        for pat in _PATTERNS:
            if pat.pattern.search(content):
                return False, pat.name
        return True, ""

    def wrap_untrusted(self, content: str, source: str = "external") -> str:
        """
        Wrap untrusted content (from files, web, tool results) in boundary
        markers so the LLM treats it as data, not instructions.

        The wrapped content is safe to include in the prompt context.
        """
        return UNTRUSTED_WRAPPER.format(source=source, content=content)

    def scan_wrapped(self, content: str) -> bool:
        """
        Scan a piece of content for injections. If wrapped, only scan the
        interior to avoid false positives on the wrapper text itself.
        """
        begin = "--- UNTRUSTED CONTENT BEGIN"
        end = "--- UNTRUSTED CONTENT END ---"

        if begin in content and end in content:
            # Extract interior and scan it
            start_idx = content.find(begin)
            # Find the first newline after begin line
            inner_start = content.find("\n", start_idx) + 1
            inner_end = content.rfind(end)
            inner = content[inner_start:inner_end]
            return self.scan(inner)

        return self.scan(content)


__all__ = ["PromptGuard", "UNTRUSTED_WRAPPER"]

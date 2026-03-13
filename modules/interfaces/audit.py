"""
modules/interfaces/audit.py - Audit logging interface.

Built-in drivers:
  sqlite → security.audit.AuditLogger  (Phase 1, default)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AuditInterface(ABC):
    """
    Contract for audit and security event logging.

    Implementations must be non-blocking and must never raise exceptions
    that would interrupt normal agent flow.
    """

    @abstractmethod
    async def log(
        self,
        level: str,
        action: str,
        user_id: str,
        detail: dict[str, Any],
        result: str,
    ) -> None:
        """
        Record an audit event.

        Args:
            level:   Severity — "info", "warning", "critical".
            action:  Short action name, e.g. "chat_request", "tool_call".
            user_id: Originating user identifier.
            detail:  Arbitrary key/value context (PII must be masked by impl).
            result:  Outcome — "success", "failure", "blocked".
        """
        ...

    @abstractmethod
    async def log_security(
        self,
        event_type: str,
        user_id: str,
        detail: str,
        source_ip: str = "",
    ) -> None:
        """
        Record a security event (injection attempt, auth failure, etc.).

        Args:
            event_type: e.g. "prompt_injection", "auth_failure", "rate_limit".
            user_id:    Originating user identifier.
            detail:     Human-readable description.
            source_ip:  Remote IP if known.
        """
        ...


__all__ = ["AuditInterface"]

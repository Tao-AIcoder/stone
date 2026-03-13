"""
security/audit.py - Audit logging for STONE (默行者)

Writes structured audit records to SQLite. All sensitive fields are
automatically redacted before storage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from models.audit import AuditLevel, AuditLog, AuditResult, SecurityEventType, SecurityLog

if TYPE_CHECKING:
    from modules.memory.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Fields that are always redacted in audit detail dicts
SENSITIVE_FIELDS = frozenset({
    "api_key", "secret", "token", "pin", "password",
    "totp", "access_token", "refresh_token", "authorization",
    "zhipuai_api_key", "dashscope_api_key", "tavily_api_key",
    "feishu_app_secret", "admin_pin", "totp_secret",
})


def _redact(detail: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of detail with sensitive keys replaced by '***'."""
    return {
        k: "***" if k.lower() in SENSITIVE_FIELDS else v
        for k, v in detail.items()
    }


class AuditLogger:
    """
    Writes audit and security events to SQLite.
    Fails gracefully (logs a warning) if storage is unavailable.
    """

    def __init__(self, sqlite_store: "SQLiteStore | None" = None) -> None:
        self.sqlite_store = sqlite_store

    async def log(
        self,
        level: str,
        action: str,
        user_id: str,
        detail: dict[str, Any] | None = None,
        result: str = "success",
        duration_ms: float = 0.0,
        conv_id: str = "",
    ) -> None:
        """
        Write a general audit log entry.

        Args:
            level:       AuditLevel value string (INFO, WARNING, ERROR, etc.)
            action:      Machine-readable action identifier
            user_id:     User who triggered the action
            detail:      Arbitrary metadata dict (sensitive keys auto-redacted)
            result:      AuditResult value string (success, failure, blocked)
            duration_ms: Execution time in milliseconds
            conv_id:     Optional conversation ID
        """
        entry = AuditLog(
            level=AuditLevel(level.upper()),
            action=action,
            user_id=user_id,
            conv_id=conv_id,
            detail=_redact(detail or {}),
            result=AuditResult(result.lower()),
            duration_ms=duration_ms,
        )

        # Always emit to Python logger
        log_fn = {
            AuditLevel.DEBUG: logger.debug,
            AuditLevel.INFO: logger.info,
            AuditLevel.WARNING: logger.warning,
            AuditLevel.ERROR: logger.error,
            AuditLevel.CRITICAL: logger.critical,
        }.get(entry.level, logger.info)

        log_fn(
            "AUDIT action=%s user=%s result=%s",
            action,
            user_id,
            result,
        )

        if self.sqlite_store is not None:
            try:
                await self.sqlite_store.save_audit_log(entry)
            except Exception as exc:
                logger.warning("AuditLogger: failed to persist audit log: %s", exc)

    async def log_security(
        self,
        event_type: str,
        source_ip: str,
        user_id: str,
        detail: str = "",
    ) -> None:
        """
        Write a security-specific event.

        Args:
            event_type: SecurityEventType value string
            source_ip:  Origin IP address (may be empty for WS connections)
            user_id:    Involved user (open_id or user_id)
            detail:     Plain text description of the event
        """
        try:
            etype = SecurityEventType(event_type.lower())
        except ValueError:
            etype = SecurityEventType.SUSPICIOUS_ACTIVITY

        entry = SecurityLog(
            event_type=etype,
            source_ip=source_ip,
            user_id=user_id,
            detail=detail,
        )

        logger.warning(
            "SECURITY event=%s user=%s detail=%s",
            event_type,
            user_id[:12] + "***" if len(user_id) > 12 else user_id,
            detail[:100],
        )

        if self.sqlite_store is not None:
            try:
                await self.sqlite_store.save_security_log(entry)
            except Exception as exc:
                logger.warning(
                    "AuditLogger: failed to persist security log: %s", exc
                )


__all__ = ["AuditLogger"]

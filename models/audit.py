"""
models/audit.py - Audit and security log models for STONE (默行者)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AuditLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AuditResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    PENDING = "pending"


class AuditLog(BaseModel):
    """General-purpose audit log entry."""

    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    level: AuditLevel = AuditLevel.INFO
    action: str                      # e.g. "tool_call", "model_request", "dry_run_confirm"
    user_id: str = "default_user"
    conv_id: str = ""

    detail: dict[str, Any] = Field(default_factory=dict)
    result: AuditResult = AuditResult.SUCCESS
    duration_ms: float = 0.0         # Execution time in milliseconds

    model_config = {"arbitrary_types_allowed": True}

    def redacted(self) -> "AuditLog":
        """Return a copy with sensitive fields stripped from detail."""
        safe_detail = {
            k: "***" if k in {"api_key", "secret", "token", "pin", "password"} else v
            for k, v in self.detail.items()
        }
        return self.model_copy(update={"detail": safe_detail})


class SecurityEventType(str, Enum):
    AUTH_FAILURE = "auth_failure"
    WHITELIST_BLOCK = "whitelist_block"
    RATE_LIMIT = "rate_limit"
    PROMPT_INJECTION = "prompt_injection"
    PIN_LOCKOUT = "pin_lockout"
    TOTP_FAILURE = "totp_failure"
    RECONNECT_FAILURE = "reconnect_failure"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"


class SecurityLog(BaseModel):
    """Security-specific event log entry."""

    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    event_type: SecurityEventType
    source_ip: str = ""
    user_id: str = ""
    open_id: str = ""

    detail: str = ""
    severity: AuditLevel = AuditLevel.WARNING

    model_config = {"arbitrary_types_allowed": True}


__all__ = [
    "AuditLevel",
    "AuditResult",
    "AuditLog",
    "SecurityEventType",
    "SecurityLog",
]

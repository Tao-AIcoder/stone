"""
models/errors.py - Complete exception hierarchy for STONE (默行者)

All custom exceptions derive from StoneError, which carries a human-readable
message and an optional machine-readable error code.
"""

from __future__ import annotations


class StoneError(Exception):
    """Base exception for all STONE errors."""

    def __init__(self, message: str, code: str = "STONE_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ── State Machine ─────────────────────────────────────────────────────────────

class InvalidStateTransition(StoneError):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(
            message=f"Invalid state transition: {from_state} -> {to_state}",
            code="INVALID_STATE_TRANSITION",
        )
        self.from_state = from_state
        self.to_state = to_state


# ── Authentication / Authorization ───────────────────────────────────────────

class AuthError(StoneError):
    """Authentication failed."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message=message, code="AUTH_ERROR")


class PermissionError(StoneError):  # noqa: A001  (shadows builtin intentionally)
    """User does not have permission to perform this action."""

    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__(message=message, code="PERMISSION_ERROR")


class PromptInjectionError(StoneError):
    """Prompt injection / jailbreak attempt detected."""

    def __init__(self, message: str = "Prompt injection detected", pattern: str = "") -> None:
        super().__init__(message=message, code="PROMPT_INJECTION")
        self.pattern = pattern


# ── Module ────────────────────────────────────────────────────────────────────

class ModuleError(StoneError):
    """Generic module-level error."""

    def __init__(self, message: str, module_name: str = "") -> None:
        super().__init__(message=message, code="MODULE_ERROR")
        self.module_name = module_name


class ModuleNotFoundError(ModuleError):  # noqa: A001
    """Requested module is not registered / cannot be found."""

    def __init__(self, module_name: str) -> None:
        super().__init__(
            message=f"Module not found: {module_name}",
            module_name=module_name,
        )
        self.code = "MODULE_NOT_FOUND"


class ModuleFallbackError(ModuleError):
    """Module failed and no fallback is available."""

    def __init__(self, module_name: str, reason: str = "") -> None:
        msg = f"Module fallback failed for {module_name}"
        if reason:
            msg += f": {reason}"
        super().__init__(message=msg, module_name=module_name)
        self.code = "MODULE_FALLBACK_FAILED"


# ── Model / LLM ───────────────────────────────────────────────────────────────

class ModelError(StoneError):
    """Generic model / LLM error."""

    def __init__(self, message: str, model_id: str = "") -> None:
        super().__init__(message=message, code="MODEL_ERROR")
        self.model_id = model_id


class ModelTimeoutError(ModelError):
    """Model request timed out."""

    def __init__(self, model_id: str, timeout_seconds: float = 0) -> None:
        msg = f"Model {model_id!r} timed out"
        if timeout_seconds:
            msg += f" after {timeout_seconds}s"
        super().__init__(message=msg, model_id=model_id)
        self.code = "MODEL_TIMEOUT"
        self.timeout_seconds = timeout_seconds


class ModelQuotaError(ModelError):
    """Model quota / rate-limit exceeded."""

    def __init__(self, model_id: str) -> None:
        super().__init__(
            message=f"Quota exceeded for model {model_id!r}",
            model_id=model_id,
        )
        self.code = "MODEL_QUOTA_EXCEEDED"


# ── Tool / Execution ──────────────────────────────────────────────────────────

class ToolError(StoneError):
    """Generic tool execution error."""

    def __init__(self, message: str, tool_name: str = "") -> None:
        super().__init__(message=message, code="TOOL_ERROR")
        self.tool_name = tool_name


class SandboxError(ToolError):
    """Error originating from the Docker sandbox."""

    def __init__(self, message: str, tool_name: str = "") -> None:
        super().__init__(message=message, tool_name=tool_name)
        self.code = "SANDBOX_ERROR"


class ToolTimeoutError(ToolError):
    """Tool execution timed out."""

    def __init__(self, tool_name: str, timeout_seconds: float = 0) -> None:
        msg = f"Tool {tool_name!r} timed out"
        if timeout_seconds:
            msg += f" after {timeout_seconds}s"
        super().__init__(message=msg, tool_name=tool_name)
        self.code = "TOOL_TIMEOUT"
        self.timeout_seconds = timeout_seconds


# ── Dry-Run ───────────────────────────────────────────────────────────────────

class DryRunRejectedError(StoneError):
    """User rejected (cancelled) a dry-run plan."""

    def __init__(self, conv_id: str = "") -> None:
        msg = "Dry-run plan was rejected by the user"
        if conv_id:
            msg += f" (conversation: {conv_id})"
        super().__init__(message=msg, code="DRY_RUN_REJECTED")
        self.conv_id = conv_id


__all__ = [
    "StoneError",
    "InvalidStateTransition",
    "AuthError",
    "PermissionError",
    "PromptInjectionError",
    "ModuleError",
    "ModuleNotFoundError",
    "ModuleFallbackError",
    "ModelError",
    "ModelTimeoutError",
    "ModelQuotaError",
    "ToolError",
    "SandboxError",
    "ToolTimeoutError",
    "DryRunRejectedError",
]

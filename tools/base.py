"""
tools/base.py - Base abstractions for all STONE tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Standardised result returned by every tool execution."""

    success: bool
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = {}

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def ok(cls, output: str, metadata: dict[str, Any] | None = None) -> "ToolResult":
        return cls(success=True, output=output, metadata=metadata or {})

    @classmethod
    def fail(cls, error: str, metadata: dict[str, Any] | None = None) -> "ToolResult":
        return cls(success=False, error=error, metadata=metadata or {})


class ToolInterface(ABC):
    """
    Abstract base class that every STONE tool must implement.
    All methods must be async.
    """

    # Unique identifier for this tool (snake_case)
    name: str = ""
    description: str = ""
    requires_confirmation: bool = False

    @abstractmethod
    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...

    def get_schema(self) -> dict[str, Any]:
        """Return the JSON Schema describing this tool's parameters."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }


__all__ = ["ToolResult", "ToolInterface"]

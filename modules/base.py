"""
modules/base.py - Abstract base class and health status for STONE modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ModuleHealth(BaseModel):
    """Health report returned by a module."""

    module_name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    message: str = ""
    details: dict[str, Any] = {}

    model_config = {"arbitrary_types_allowed": True}


class StoneModule(ABC):
    """
    Abstract base class for all STONE modules.

    Lifecycle: initialize() → [use] → shutdown()
    """

    module_name: str = "unnamed_module"

    @abstractmethod
    async def initialize(self) -> None:
        """Perform async setup. Called once at startup."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources. Called on graceful shutdown."""
        ...

    @abstractmethod
    async def health_check(self) -> ModuleHealth:
        """Return the current health status of this module."""
        ...


__all__ = ["HealthStatus", "ModuleHealth", "StoneModule"]

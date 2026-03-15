"""
modules/interfaces/mcp_server.py - MCP Server interface for STONE (默行者)

Defines the contract for all MCP (Model Context Protocol) server integrations.
STONE acts as MCP Client; each external service runs as an MCP Server process.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPTool:
    """Description of a tool exposed by an MCP Server."""
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResult:
    """Result from calling an MCP tool."""
    success: bool
    content: Any = None       # tool output (string, dict, list…)
    error: str = ""
    is_error: bool = False


class MCPServerInterface(ABC):
    """
    Abstract interface for MCP Server integrations.

    Each implementation wraps one external MCP Server process/endpoint
    (e.g. Evernote CN MCP Server, Baidu Netdisk MCP Server).

    Lifecycle:
        await server.connect()
        tools = await server.list_tools()
        result = await server.call_tool("tool_name", {...})
        await server.disconnect()
    """

    # Unique name for this MCP server (used in stone.config.json)
    server_name: str = ""

    @abstractmethod
    async def connect(self) -> None:
        """Start the MCP Server process and establish connection."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully stop the MCP Server process."""
        ...

    @abstractmethod
    async def list_tools(self) -> list[MCPTool]:
        """Return the list of tools this server exposes."""
        ...

    @abstractmethod
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPResult:
        """Invoke a tool on the MCP Server and return the result."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the server process is running and connection is active."""
        ...


__all__ = ["MCPTool", "MCPResult", "MCPServerInterface"]

"""
registry/mcp_manager.py - MCP (Model Context Protocol) manager stub for STONE.

TODO: Phase 2 - implement MCP server/client integration.

MCP would allow STONE to:
- Expose its tools as MCP servers to other MCP clients
- Connect to external MCP servers to gain additional capabilities
- Support the Anthropic Model Context Protocol spec for tool interop

Planned architecture (Phase 2):
- MCPServerAdapter: wraps ToolInterface for MCP exposure
- MCPClientAdapter: wraps external MCP servers as ToolInterface
- MCPRegistry: manages multiple MCP connections
- Auto-discovery of MCP tools and registration in SkillRegistry
"""

from __future__ import annotations


class MCPManager:
    """
    TODO: Phase 2 - implement MCP protocol integration.

    Planned methods:
    - connect_server(url: str, name: str) -> MCPConnection
    - disconnect_server(name: str) -> None
    - list_mcp_tools() -> list[dict]
    - call_mcp_tool(name: str, params: dict) -> str
    - expose_as_mcp_server(port: int) -> None
    """

    async def initialize(self) -> None:
        raise NotImplementedError("MCPManager not implemented (Phase 2)")

    async def shutdown(self) -> None:
        pass


__all__ = ["MCPManager"]

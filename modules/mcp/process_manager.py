"""
modules/mcp/process_manager.py - MCP Server process lifecycle manager for STONE.

Reads mcp_servers config from stone.config.json, starts enabled servers,
monitors health, and provides a unified tool dispatch interface.

Usage (in main.py lifespan):
    mcp_manager = MCPProcessManager(mcp_config)
    await mcp_manager.start_all()
    ...
    await mcp_manager.stop_all()

Tool dispatch (in note_tool, memory_tool, etc.):
    result = await mcp_manager.call("evernote", "create_note", {...})
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.interfaces.mcp_server import MCPResult, MCPTool
from modules.mcp.client import StdioMCPClient

logger = logging.getLogger(__name__)


class MCPProcessManager:
    """
    Manages the lifecycle of all configured MCP Server processes.

    Config format (stone.config.json):
        "mcp_servers": {
            "evernote": {
                "enabled": true,
                "command": "npx",
                "args": ["@evernote/mcp-server"],
                "env": {"EVERNOTE_TOKEN": ""}
            },
            "baidu_netdisk": {
                "enabled": false,
                "command": "npx",
                "args": ["@baidu/netdisk-mcp-server"],
                "env": {"BAIDU_ACCESS_TOKEN": ""}
            }
        }
    """

    def __init__(self, mcp_config: dict[str, Any]) -> None:
        self._config = mcp_config or {}
        self._clients: dict[str, StdioMCPClient] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start all enabled MCP servers."""
        for name, cfg in self._config.items():
            if not cfg.get("enabled", False):
                logger.debug("MCP[%s]: disabled, skipping", name)
                continue
            await self._start_server(name, cfg)

    async def _start_server(self, name: str, cfg: dict[str, Any]) -> None:
        command = cfg.get("command", "")
        if not command:
            logger.warning("MCP[%s]: no command configured, skipping", name)
            return
        args = cfg.get("args", [])
        env = cfg.get("env", {})
        timeout = cfg.get("timeout", 30.0)
        client = StdioMCPClient(
            server_name=name,
            command=command,
            args=args,
            env=env,
            timeout=timeout,
        )
        try:
            await client.connect()
            self._clients[name] = client
            logger.info("MCP[%s]: started OK", name)
        except Exception as exc:
            logger.error("MCP[%s]: failed to start: %s", name, exc)

    async def stop_all(self) -> None:
        """Gracefully stop all running MCP servers."""
        tasks = [client.disconnect() for client in self._clients.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._clients.clear()
        logger.info("MCPProcessManager: all servers stopped")

    async def restart(self, server_name: str) -> bool:
        """Restart a specific MCP server. Returns True on success."""
        if server_name in self._clients:
            await self._clients[server_name].disconnect()
            del self._clients[server_name]
        cfg = self._config.get(server_name)
        if not cfg:
            return False
        await self._start_server(server_name, cfg)
        return server_name in self._clients

    # ── Status ────────────────────────────────────────────────────────────────

    def list_servers(self) -> dict[str, bool]:
        """Return {server_name: is_connected} for all configured servers."""
        result: dict[str, bool] = {}
        for name in self._config:
            if not self._config[name].get("enabled", False):
                result[name] = False
            else:
                client = self._clients.get(name)
                result[name] = client.is_connected if client else False
        return result

    def get_client(self, server_name: str) -> StdioMCPClient | None:
        return self._clients.get(server_name)

    # ── Tool Dispatch ─────────────────────────────────────────────────────────

    async def list_tools(self, server_name: str) -> list[MCPTool]:
        client = self._clients.get(server_name)
        if not client or not client.is_connected:
            return []
        return await client.list_tools()

    async def call(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPResult:
        """Call a tool on the specified MCP server."""
        client = self._clients.get(server_name)
        if not client:
            return MCPResult(
                success=False,
                error=f"MCP server '{server_name}' 未启动或未配置",
                is_error=True,
            )
        if not client.is_connected:
            # Try reconnect once
            logger.warning("MCP[%s]: not connected, attempting reconnect", server_name)
            if not await self.restart(server_name):
                return MCPResult(
                    success=False,
                    error=f"MCP server '{server_name}' 连接断开且重连失败",
                    is_error=True,
                )
            client = self._clients[server_name]
        return await client.call_tool(tool_name, arguments)

    async def all_tools(self) -> dict[str, list[MCPTool]]:
        """Return all tools from all connected servers."""
        result: dict[str, list[MCPTool]] = {}
        for name, client in self._clients.items():
            if client.is_connected:
                try:
                    result[name] = await client.list_tools()
                except Exception as exc:
                    logger.warning("MCP[%s]: list_tools failed: %s", name, exc)
        return result


__all__ = ["MCPProcessManager"]

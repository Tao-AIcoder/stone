"""
modules/mcp/client.py - MCP (Model Context Protocol) Client for STONE.

Implements the MCPServerInterface by communicating with an MCP Server
subprocess via stdio (JSON-RPC 2.0 over stdin/stdout).

Protocol reference: https://modelcontextprotocol.io/specification

Supports:
  - stdio transport (default): spawns server as subprocess
  - SSE transport: connects to an HTTP+SSE endpoint (future)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from modules.interfaces.mcp_server import MCPResult, MCPServerInterface, MCPTool

logger = logging.getLogger(__name__)

# JSON-RPC method names (MCP spec)
_METHOD_INITIALIZE = "initialize"
_METHOD_LIST_TOOLS = "tools/list"
_METHOD_CALL_TOOL = "tools/call"


class StdioMCPClient(MCPServerInterface):
    """
    MCP Client that communicates with an MCP Server via stdio (subprocess).

    The server process is started with the configured command + args.
    Communication uses newline-delimited JSON-RPC 2.0.

    Usage:
        client = StdioMCPClient(
            server_name="evernote",
            command="npx",
            args=["@evernote/mcp-server"],
            env={"EVERNOTE_TOKEN": "xxx"},
        )
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("create_note", {"title": "...", "content": "..."})
        await client.disconnect()
    """

    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._server_name = server_name
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._connected = False
        self._tools_cache: list[MCPTool] | None = None

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def is_connected(self) -> bool:
        return self._connected and (
            self._process is not None and self._process.returncode is None
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Start the MCP Server subprocess and perform MCP handshake."""
        import os
        env = {**os.environ, **self._env}
        cmd = [self._command] + self._args
        logger.info("MCP[%s]: starting process: %s", self._server_name, " ".join(cmd))
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        # MCP handshake: send initialize
        resp = await self._rpc(_METHOD_INITIALIZE, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "stone-mcp-client", "version": "0.1.0"},
        })
        if "error" in resp:
            raise RuntimeError(
                f"MCP[{self._server_name}] init failed: {resp['error']}"
            )
        self._connected = True
        logger.info("MCP[%s]: connected OK", self._server_name)

    async def disconnect(self) -> None:
        self._connected = False
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except Exception:
                self._process.kill()
        logger.info("MCP[%s]: disconnected", self._server_name)

    # ── Tool Discovery ────────────────────────────────────────────────────────

    async def list_tools(self) -> list[MCPTool]:
        if self._tools_cache is not None:
            return self._tools_cache
        resp = await self._rpc(_METHOD_LIST_TOOLS, {})
        tools_raw = resp.get("result", {}).get("tools", [])
        tools = [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools_raw
        ]
        self._tools_cache = tools
        logger.debug("MCP[%s]: discovered %d tools", self._server_name, len(tools))
        return tools

    # ── Tool Invocation ───────────────────────────────────────────────────────

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPResult:
        resp = await self._rpc(_METHOD_CALL_TOOL, {
            "name": tool_name,
            "arguments": arguments,
        })
        if "error" in resp:
            return MCPResult(
                success=False,
                error=str(resp["error"]),
                is_error=True,
            )
        result = resp.get("result", {})
        content = result.get("content", result)
        is_error = result.get("isError", False)
        # Extract text from content array (MCP spec)
        if isinstance(content, list):
            text_parts = [
                c.get("text", "") for c in content if c.get("type") == "text"
            ]
            content = "\n".join(text_parts) if text_parts else str(content)
        return MCPResult(
            success=not is_error,
            content=content,
            is_error=is_error,
        )

    # ── JSON-RPC Transport ────────────────────────────────────────────────────

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise RuntimeError(f"MCP[{self._server_name}]: process not running")
        req_id = str(uuid.uuid4())
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }, ensure_ascii=False)
        self._process.stdin.write((request + "\n").encode())
        await self._process.stdin.drain()

        # Read response line with timeout
        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"MCP[{self._server_name}]: timeout waiting for response to {method!r}"
            )
        if not line:
            stderr = b""
            if self._process.stderr:
                try:
                    stderr = await asyncio.wait_for(
                        self._process.stderr.read(4096), timeout=2.0
                    )
                except Exception:
                    pass
            raise RuntimeError(
                f"MCP[{self._server_name}]: server closed connection. "
                f"stderr: {stderr.decode(errors='replace')[:200]}"
            )
        return json.loads(line.decode())


__all__ = ["StdioMCPClient"]

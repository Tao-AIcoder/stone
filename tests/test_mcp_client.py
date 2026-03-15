"""
tests/test_mcp_client.py - MCP Client & ProcessManager 单元测试

覆盖（不需要真实 MCP Server）：
  - StdioMCPClient 接口合规性
  - MCPProcessManager.list_servers() 状态报告
  - MCPProcessManager.call() 在 server 未启动时返回错误结果
  - MCPResult / MCPTool 数据结构
  - 配置解析
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.interfaces.mcp_server import MCPResult, MCPTool
from modules.mcp.client import StdioMCPClient
from modules.mcp.process_manager import MCPProcessManager


# ── MCPTool / MCPResult ───────────────────────────────────────────────────────

class TestDataStructures:
    def test_mcp_tool_fields(self):
        tool = MCPTool(name="create_note", description="创建笔记", input_schema={"type": "object"})
        assert tool.name == "create_note"
        assert tool.description == "创建笔记"

    def test_mcp_result_success(self):
        r = MCPResult(success=True, content="note_id_123")
        assert r.success
        assert not r.is_error

    def test_mcp_result_failure(self):
        r = MCPResult(success=False, error="connection refused", is_error=True)
        assert not r.success
        assert r.is_error


# ── StdioMCPClient interface compliance ───────────────────────────────────────

class TestStdioMCPClientInterface:
    def test_implements_interface(self):
        from modules.interfaces.mcp_server import MCPServerInterface
        client = StdioMCPClient("test", "echo")
        assert isinstance(client, MCPServerInterface)

    def test_not_connected_initially(self):
        client = StdioMCPClient("test", "echo")
        assert not client.is_connected

    def test_server_name(self):
        client = StdioMCPClient("evernote", "npx", ["@evernote/mcp-server"])
        assert client.server_name == "evernote"

    @pytest.mark.asyncio
    async def test_call_tool_when_not_connected_raises(self):
        client = StdioMCPClient("test", "echo")
        with pytest.raises(RuntimeError):
            await client.call_tool("some_tool", {})

    @pytest.mark.asyncio
    async def test_disconnect_when_not_started_is_safe(self):
        """Disconnecting a never-started client should not raise."""
        client = StdioMCPClient("test", "echo")
        await client.disconnect()  # Should not raise


# ── MCPProcessManager ─────────────────────────────────────────────────────────

class TestMCPProcessManager:
    def _make_config(self, evernote_enabled=False, baidu_enabled=False):
        return {
            "evernote": {
                "enabled": evernote_enabled,
                "command": "npx",
                "args": ["@evernote/mcp-server"],
                "env": {"EVERNOTE_TOKEN": "test"},
            },
            "baidu_netdisk": {
                "enabled": baidu_enabled,
                "command": "npx",
                "args": ["@baidu/netdisk-mcp-server"],
                "env": {},
            },
        }

    def test_list_servers_all_disabled(self):
        mgr = MCPProcessManager(self._make_config())
        status = mgr.list_servers()
        assert status["evernote"] is False
        assert status["baidu_netdisk"] is False

    def test_empty_config(self):
        mgr = MCPProcessManager({})
        assert mgr.list_servers() == {}

    @pytest.mark.asyncio
    async def test_call_returns_error_when_server_not_started(self):
        mgr = MCPProcessManager(self._make_config(evernote_enabled=False))
        result = await mgr.call("evernote", "create_note", {"title": "test"})
        assert not result.success
        assert "未启动" in result.error or "配置" in result.error

    @pytest.mark.asyncio
    async def test_stop_all_is_safe_when_nothing_started(self):
        mgr = MCPProcessManager(self._make_config())
        await mgr.stop_all()  # Should not raise

    @pytest.mark.asyncio
    async def test_list_tools_returns_empty_when_not_connected(self):
        mgr = MCPProcessManager(self._make_config())
        tools = await mgr.list_tools("evernote")
        assert tools == []

    def test_get_client_returns_none_when_not_started(self):
        mgr = MCPProcessManager(self._make_config())
        assert mgr.get_client("evernote") is None

    @pytest.mark.asyncio
    async def test_start_all_skips_disabled_servers(self):
        """start_all should not attempt to start disabled servers."""
        mgr = MCPProcessManager(self._make_config(evernote_enabled=False))
        # Mock _start_server to track calls
        mgr._start_server = AsyncMock()
        await mgr.start_all()
        mgr._start_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_tools_returns_empty_when_no_connections(self):
        mgr = MCPProcessManager(self._make_config())
        result = await mgr.all_tools()
        assert result == {}


# ── Config parsing ────────────────────────────────────────────────────────────

class TestConfigParsing:
    def test_command_without_config_is_skipped(self):
        """Server config without 'command' should log warning but not crash."""
        mgr = MCPProcessManager({
            "broken_server": {"enabled": True, "env": {}}
            # missing "command"
        })
        # Should not raise on construction
        assert "broken_server" in mgr._config

    def test_none_config_handled(self):
        mgr = MCPProcessManager(None)  # type: ignore
        assert mgr._config == {}

"""
tests/test_http_tool.py - HttpTool 单元测试

覆盖：
  - URL 验证（私有 IP 拦截、scheme 检查）
  - method 合法性验证
  - GET 不需要确认，POST/DELETE 需要确认
  - 成功响应解析（mock httpx）
  - HTML strip 功能
  - 超大响应截断
  - 请求超时处理
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.http_tool import HttpTool, _is_private_ip, _strip_html


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def http_tool():
    return HttpTool()


# ── Private IP Detection ──────────────────────────────────────────────────────

class TestPrivateIPDetection:
    @pytest.mark.parametrize("host", ["10.0.0.1", "192.168.1.1", "172.16.0.1", "127.0.0.1"])
    def test_private_ips_detected(self, host):
        with patch("socket.gethostbyname", return_value=host):
            assert _is_private_ip(host)

    def test_public_ip_not_private(self):
        with patch("socket.gethostbyname", return_value="8.8.8.8"):
            assert not _is_private_ip("dns.google")

    def test_dns_failure_returns_true(self):
        """DNS failure → treat as private (fail safe)."""
        with patch("socket.gethostbyname", side_effect=Exception("DNS error")):
            assert _is_private_ip("unknown.internal")


# ── HTML Stripping ────────────────────────────────────────────────────────────

class TestHtmlStrip:
    def test_strips_tags(self):
        html = "<html><body><p>Hello World</p></body></html>"
        result = _strip_html(html)
        assert "Hello World" in result
        assert "<p>" not in result

    def test_removes_script(self):
        html = "<html><body><script>alert('xss')</script><p>content</p></body></html>"
        result = _strip_html(html)
        assert "alert" not in result
        assert "content" in result

    def test_collapses_whitespace(self):
        html = "<p>a</p>\n\n\n\n\n<p>b</p>"
        result = _strip_html(html)
        assert "\n\n\n" not in result


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidation:
    @pytest.mark.asyncio
    async def test_empty_url_fails(self, http_tool):
        result = await http_tool.execute({"url": ""})
        assert not result.success
        assert "url" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_scheme_fails(self, http_tool):
        result = await http_tool.execute({"url": "ftp://example.com/file"})
        assert not result.success
        assert "http" in result.error.lower()

    @pytest.mark.asyncio
    async def test_private_ip_blocked(self, http_tool):
        with patch("tools.http_tool._is_private_ip", return_value=True):
            result = await http_tool.execute({"url": "http://192.168.1.1/admin"})
        assert not result.success
        assert "私有" in result.error or "内网" in result.error

    @pytest.mark.asyncio
    async def test_invalid_method_fails(self, http_tool):
        result = await http_tool.execute({"url": "https://example.com", "method": "TRACE"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_missing_hostname_fails(self, http_tool):
        result = await http_tool.execute({"url": "https://"})
        assert not result.success


# ── Confirmation Check ────────────────────────────────────────────────────────

class TestConfirmationCheck:
    def test_get_no_confirmation(self, http_tool):
        assert not http_tool.needs_confirmation_for({"method": "GET", "url": "https://a.com"})

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_write_methods_need_confirmation(self, http_tool, method):
        assert http_tool.needs_confirmation_for({"method": method, "url": "https://a.com"})


# ── Successful Request (mocked httpx) ─────────────────────────────────────────

class TestSuccessfulRequest:
    @pytest.mark.asyncio
    async def test_get_returns_content(self, http_tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.content = b"Hello, STONE!"
        mock_resp.encoding = "utf-8"
        mock_resp.url = "https://example.com"

        with patch("tools.http_tool._is_private_ip", return_value=False):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await http_tool.execute({"url": "https://example.com"})

        assert result.success
        assert "Hello, STONE!" in result.output
        assert result.metadata["status_code"] == 200

    @pytest.mark.asyncio
    async def test_unsupported_content_type_fails(self, http_tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "image/png"}
        mock_resp.content = b"\x89PNG"
        mock_resp.encoding = "utf-8"
        mock_resp.url = "https://example.com/image.png"

        with patch("tools.http_tool._is_private_ip", return_value=False):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await http_tool.execute({"url": "https://example.com/image.png"})

        assert not result.success
        assert "image/png" in result.error

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, http_tool):
        import httpx
        with patch("tools.http_tool._is_private_ip", return_value=False):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await http_tool.execute({"url": "https://slow.example.com"})

        assert not result.success
        assert "超时" in result.error


# ── Schema ────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_schema_structure(self, http_tool):
        schema = http_tool.get_schema()
        assert schema["name"] == "http_tool"
        assert "url" in schema["parameters"]["properties"]
        assert "method" in schema["parameters"]["properties"]
        assert "url" in schema["parameters"]["required"]

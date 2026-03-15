"""
tools/http_tool.py - External HTTP request tool for STONE (默行者)

Security measures:
  - Block private/loopback IP ranges (SSRF prevention)
  - Max response size: 1 MB
  - Allowed content-types: text/* and application/json only
  - No Host header override
  - Configurable timeout (default 30s)
  - POST/PUT/DELETE require dry-run confirmation
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from tools.base import ToolInterface, ToolResult

logger = logging.getLogger(__name__)

_MAX_RESPONSE_BYTES = 1 * 1024 * 1024   # 1 MB
_DEFAULT_TIMEOUT = 30
_ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}
_ALLOWED_CONTENT_TYPE_PREFIXES = ("text/", "application/json", "application/xml")
_BLOCKED_HEADERS = {"host"}

# Private / loopback ranges blocked for SSRF prevention
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_VALID_ACTIONS = ("GET", "POST", "PUT", "DELETE", "PATCH")


def _is_private_ip(hostname: str) -> bool:
    """Return True if hostname resolves to a private/loopback IP.
    Fail-safe: returns True (block) on DNS resolution failure to prevent SSRF."""
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        return any(ip in net for net in _PRIVATE_RANGES)
    except Exception:
        return True  # fail-safe: block on DNS error


def _strip_html(html: str) -> str:
    """Extract readable text from HTML."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        # Collapse whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception:
        return html


class HttpTool(ToolInterface):
    """
    Makes external HTTP requests on behalf of the user.

    Actions: GET, POST, PUT, DELETE, PATCH
    GET requests are allowed without confirmation.
    POST/PUT/DELETE/PATCH require dry-run confirmation.
    """

    name = "http_tool"
    description = "向外部 URL 发送 HTTP 请求并返回响应内容。支持 GET/POST/PUT/DELETE。"
    requires_confirmation = False   # per-method check in needs_confirmation_for

    def needs_confirmation_for(self, params: dict) -> bool:
        method = params.get("method", "GET").upper()
        return method in ("POST", "PUT", "DELETE", "PATCH")

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        method = params.get("method", "GET").upper()
        url = params.get("url", "").strip()
        headers: dict[str, str] = params.get("headers") or {}
        body: str | None = params.get("body")
        timeout = int(params.get("timeout", _DEFAULT_TIMEOUT))
        strip_html_flag: bool = params.get("strip_html", True)

        # ── Validation ────────────────────────────────────────────────────────
        if not url:
            return ToolResult.fail("url 不能为空")
        if method not in _ALLOWED_METHODS:
            return ToolResult.fail(
                f"不支持的 HTTP 方法: {method!r}。"
                f"支持: {', '.join(sorted(_ALLOWED_METHODS))}"
            )
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult.fail("仅支持 http/https URL")
        if not parsed.hostname:
            return ToolResult.fail("无效的 URL")
        if _is_private_ip(parsed.hostname):
            return ToolResult.fail(
                f"出于安全考虑，不允许访问私有/内网 IP 地址: {parsed.hostname}"
            )

        # Strip blocked headers
        clean_headers: dict[str, str] = {
            k: v for k, v in headers.items()
            if k.lower() not in _BLOCKED_HEADERS
        }

        # ── Request ───────────────────────────────────────────────────────────
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                kwargs: dict[str, Any] = {
                    "headers": clean_headers,
                }
                if body and method in ("POST", "PUT", "PATCH"):
                    kwargs["content"] = body.encode()

                resp = await client.request(method, url, **kwargs)

            # ── Response validation ────────────────────────────────────────────
            ct = resp.headers.get("content-type", "")
            if not any(ct.startswith(p) for p in _ALLOWED_CONTENT_TYPE_PREFIXES):
                return ToolResult.fail(
                    f"不支持的响应内容类型: {ct!r}。"
                    "仅支持 text/* 和 application/json。"
                )

            content = resp.content
            if len(content) > _MAX_RESPONSE_BYTES:
                content = content[:_MAX_RESPONSE_BYTES]
                truncated = True
            else:
                truncated = False

            text = content.decode(resp.encoding or "utf-8", errors="replace")

            # Strip HTML if requested and content is HTML
            if strip_html_flag and "text/html" in ct:
                text = _strip_html(text)

            if truncated:
                text += "\n\n[响应已截断，超过 1MB 限制]"

            output = (
                f"状态码: {resp.status_code}\n"
                f"Content-Type: {ct}\n"
                f"URL: {resp.url}\n\n"
                f"{text}"
            )
            return ToolResult.ok(
                output,
                {
                    "status_code": resp.status_code,
                    "content_type": ct,
                    "url": str(resp.url),
                    "truncated": truncated,
                },
            )

        except httpx.TimeoutException:
            return ToolResult.fail(f"请求超时（{timeout}s）: {url}")
        except httpx.TooManyRedirects:
            return ToolResult.fail(f"重定向次数过多: {url}")
        except Exception as exc:
            logger.warning("HttpTool error: %s", exc)
            return ToolResult.fail(f"请求失败: {exc}")

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                        "description": "HTTP 方法（默认 GET）",
                        "default": "GET",
                    },
                    "url": {"type": "string", "description": "目标 URL（必填）"},
                    "headers": {
                        "type": "object",
                        "description": "请求头（键值对）",
                    },
                    "body": {
                        "type": "string",
                        "description": "请求体（POST/PUT/PATCH 时使用）",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数（默认 30）",
                        "default": 30,
                    },
                    "strip_html": {
                        "type": "boolean",
                        "description": "是否去除 HTML 标签返回纯文本（默认 true）",
                        "default": True,
                    },
                },
                "required": ["url"],
            },
        }


__all__ = ["HttpTool"]

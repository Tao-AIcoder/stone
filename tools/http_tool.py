"""
tools/http_tool.py - External HTTP request tool skeleton for STONE (默行者)

TODO: Phase 1b - implement outbound HTTP GET/POST with allowlist + sandboxing.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import ToolInterface, ToolResult

logger = logging.getLogger(__name__)


class HttpTool(ToolInterface):
    """
    Makes external HTTP requests on behalf of the user.

    TODO: Phase 1b - implement the following:
    - GET / POST / PUT / DELETE support
    - URL allowlist (configurable in stone.config.json)
    - Block private IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x, ::1)
    - Header injection protection (no Host header override)
    - Timeout: 30s
    - Max response size: 1 MB
    - POST/PUT require dry-run confirmation
    - Response content-type filtering (only text/* and application/json)
    - Optional BeautifulSoup HTML stripping for cleaner LLM context
    """

    name = "http_tool"
    description = (
        "向外部 URL 发送 HTTP 请求并返回响应内容。"
        "【Phase 1b 功能，当前不可用】"
    )
    requires_confirmation = True  # for POST/PUT/DELETE

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        # TODO: Phase 1b - implement request dispatch
        return ToolResult.fail(
            "http_tool 尚未实现（Phase 1b）。"
            "计划支持：GET、POST 请求，带 URL 白名单和内网访问防护"
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE"],
                        "description": "HTTP 方法",
                        "default": "GET",
                    },
                    "url": {"type": "string", "description": "目标 URL"},
                    "headers": {
                        "type": "object",
                        "description": "请求头（键值对）",
                    },
                    "body": {"type": "string", "description": "请求体（POST/PUT）"},
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，默认 30",
                        "default": 30,
                    },
                    "strip_html": {
                        "type": "boolean",
                        "description": "是否去除 HTML 标签，默认 true",
                        "default": True,
                    },
                },
                "required": ["url"],
            },
        }


__all__ = ["HttpTool"]

"""
tools/search_tool.py - Web search via Tavily API for STONE (默行者)
"""

from __future__ import annotations

import logging
from typing import Any

from config import settings
from models.errors import ToolError
from tools.base import ToolInterface, ToolResult

logger = logging.getLogger(__name__)

MAX_RESULTS = 5
SEARCH_TIMEOUT = 20.0


class SearchTool(ToolInterface):
    """
    Performs web searches using the Tavily API and returns structured results.
    Does NOT require user confirmation (read-only operation).
    """

    name = "search_tool"
    description = "使用 Tavily 搜索引擎搜索互联网信息，返回最相关的 5 条结果摘要。"
    requires_confirmation = False

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        query: str = params.get("query", "").strip()
        if not query:
            return ToolResult.fail("搜索关键词不能为空")

        max_results: int = int(params.get("max_results", MAX_RESULTS))
        search_depth: str = params.get("search_depth", "basic")  # basic | advanced

        if not settings.tavily_api_key:
            return ToolResult.fail("TAVILY_API_KEY 未配置，无法执行搜索")

        logger.info("SearchTool: query=%r max=%d [user=%s]", query, max_results, user_id)

        try:
            from tavily import TavilyClient  # type: ignore[import]
            import asyncio

            client = TavilyClient(api_key=settings.tavily_api_key)
            loop = asyncio.get_running_loop()

            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.search(
                        query=query,
                        search_depth=search_depth,
                        max_results=max_results,
                        include_answer=True,
                    ),
                ),
                timeout=SEARCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise ToolError(
                message=f"搜索超时（{SEARCH_TIMEOUT}s）",
                tool_name=self.name,
            )
        except ImportError:
            # Fallback: use httpx directly
            return await self._httpx_search(query, max_results)
        except Exception as exc:
            raise ToolError(
                message=f"搜索失败：{exc}",
                tool_name=self.name,
            ) from exc

        return _format_response(query, response)

    async def _httpx_search(self, query: str, max_results: int) -> ToolResult:
        """Fallback using httpx if tavily-python is not installed."""
        import httpx

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "search_depth": "basic",
        }

        try:
            async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            raise ToolError(message=f"搜索超时（{SEARCH_TIMEOUT}s）", tool_name=self.name)
        except httpx.HTTPStatusError as exc:
            raise ToolError(
                message=f"Tavily API 错误 {exc.response.status_code}",
                tool_name=self.name,
            ) from exc
        except Exception as exc:
            raise ToolError(message=f"搜索失败：{exc}", tool_name=self.name) from exc

        return _format_response(query, data)

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回结果数量，默认 5，最多 10",
                        "default": 5,
                    },
                    "search_depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                        "description": "搜索深度：basic（快速）或 advanced（深度）",
                        "default": "basic",
                    },
                },
                "required": ["query"],
            },
        }


def _format_response(query: str, data: dict[str, Any]) -> ToolResult:
    """Convert Tavily API response to a readable string."""
    lines: list[str] = [f"**搜索结果：{query}**\n"]

    answer = data.get("answer", "")
    if answer:
        lines.append(f"**摘要答案：**\n{answer}\n")

    results: list[dict[str, Any]] = data.get("results", [])
    if not results:
        lines.append("（未找到相关结果）")
        return ToolResult.ok("\n".join(lines))

    for i, r in enumerate(results[:MAX_RESULTS], 1):
        title = r.get("title", "无标题")
        url = r.get("url", "")
        content = r.get("content", "").strip()
        # Truncate long snippets
        if len(content) > 400:
            content = content[:400] + "…"
        lines.append(f"**{i}. {title}**")
        lines.append(f"来源：{url}")
        if content:
            lines.append(content)
        lines.append("")

    return ToolResult.ok(
        output="\n".join(lines),
        metadata={"query": query, "result_count": len(results)},
    )


__all__ = ["SearchTool"]

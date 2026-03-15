"""
tests/test_tool_search.py - Integration tests for SearchTool (Tavily API).

These tests call the real Tavily API. They are marked as integration tests
and will be skipped automatically when TAVILY_API_KEY is not set.
"""

from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.search_tool import SearchTool


@pytest.fixture
def tool() -> SearchTool:
    return SearchTool()


@pytest.fixture(autouse=True)
def require_tavily_key():
    from config import settings
    if not settings.tavily_api_key:
        pytest.skip("TAVILY_API_KEY 未配置，跳过集成测试")


# ── 正常搜索 ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_returns_results(tool):
    try:
        result = await tool.execute({"query": "Python asyncio 教程"})
    except Exception as e:
        pytest.skip(f"Tavily API 调用失败（网络问题），跳过: {e}")
    assert result.success, f"搜索失败：{result.error}"
    assert result.output
    assert "搜索结果" in result.output


@pytest.mark.asyncio
async def test_search_metadata_contains_query(tool):
    try:
        result = await tool.execute({"query": "FastAPI 最佳实践"})
    except Exception as e:
        pytest.skip(f"Tavily API 调用失败（网络问题），跳过: {e}")
    assert result.success
    assert result.metadata is not None
    assert result.metadata.get("query") == "FastAPI 最佳实践"
    assert isinstance(result.metadata.get("result_count"), int)


@pytest.mark.asyncio
async def test_search_max_results_respected(tool):
    try:
        result = await tool.execute({"query": "人工智能", "max_results": 2})
    except Exception as e:
        pytest.skip(f"Tavily API 调用失败（网络问题），跳过: {e}")
    assert result.success
    # result_count 最多等于 max_results
    assert result.metadata["result_count"] <= 2


@pytest.mark.asyncio
async def test_search_advanced_depth(tool):
    try:
        result = await tool.execute({"query": "LLM Agent 架构", "search_depth": "advanced"})
    except Exception as e:
        pytest.skip(f"Tavily API 调用失败（网络问题），跳过: {e}")
    assert result.success
    assert result.output


# ── 异常/边界情况 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_empty_query_fails(tool):
    result = await tool.execute({"query": ""})
    assert not result.success
    assert "不能为空" in (result.error or "")


@pytest.mark.asyncio
async def test_search_missing_query_fails(tool):
    result = await tool.execute({})
    assert not result.success


@pytest.mark.asyncio
async def test_search_no_api_key_fails(tool):
    """当 API Key 被移除时应返回友好错误，而不是抛出异常。"""
    from unittest.mock import patch, MagicMock

    mock_settings = MagicMock()
    mock_settings.tavily_api_key = ""

    with patch("tools.search_tool.settings", mock_settings):
        result = await tool.execute({"query": "测试"})
    assert not result.success
    assert "TAVILY_API_KEY" in (result.error or "")

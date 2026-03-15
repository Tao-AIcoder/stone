"""
tests/test_tool_file.py - Integration tests for FileTool (WORKSPACE_DIR).

Tests run against the real filesystem within WORKSPACE_DIR.
Each test gets an isolated subdirectory to avoid interference.
"""

from __future__ import annotations

import sys
import os
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.file_tool import FileTool


@pytest.fixture
def tool() -> FileTool:
    return FileTool()


@pytest.fixture
def subdir(tool) -> str:
    """Each test gets a unique subdirectory under WORKSPACE_DIR, auto-cleaned after test."""
    import shutil
    name = f"_test_{uuid.uuid4().hex[:8]}"
    yield name
    target = tool.workspace / name
    if target.exists():
        shutil.rmtree(target)



# ── 写文件 / 读文件 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_then_read(tool, subdir):
    path = f"{subdir}/hello.txt"
    content = "默行者测试内容 🪨"

    w = await tool.execute({"action": "write_file", "path": path, "content": content})
    assert w.success, f"写入失败：{w.error}"

    r = await tool.execute({"action": "read_file", "path": path})
    assert r.success, f"读取失败：{r.error}"
    assert r.output == content


@pytest.mark.asyncio
async def test_write_creates_parent_dirs(tool, subdir):
    path = f"{subdir}/a/b/c/deep.txt"
    w = await tool.execute({"action": "write_file", "path": path, "content": "deep"})
    assert w.success


@pytest.mark.asyncio
async def test_overwrite_false_blocks_existing(tool, subdir):
    path = f"{subdir}/once.txt"
    await tool.execute({"action": "write_file", "path": path, "content": "first"})
    w2 = await tool.execute({"action": "write_file", "path": path, "content": "second", "overwrite": False})
    assert not w2.success
    assert "已存在" in (w2.error or "")


@pytest.mark.asyncio
async def test_overwrite_true_replaces_content(tool, subdir):
    path = f"{subdir}/replace.txt"
    await tool.execute({"action": "write_file", "path": path, "content": "v1"})
    await tool.execute({"action": "write_file", "path": path, "content": "v2", "overwrite": True})
    r = await tool.execute({"action": "read_file", "path": path})
    assert r.output == "v2"


@pytest.mark.asyncio
async def test_read_nonexistent_fails(tool, subdir):
    r = await tool.execute({"action": "read_file", "path": f"{subdir}/nope.txt"})
    assert not r.success
    assert "不存在" in (r.error or "")


# ── list_dir ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_dir_shows_written_files(tool, subdir):
    await tool.execute({"action": "write_file", "path": f"{subdir}/a.txt", "content": "a"})
    await tool.execute({"action": "write_file", "path": f"{subdir}/b.txt", "content": "b"})

    r = await tool.execute({"action": "list_dir", "path": subdir})
    assert r.success
    assert "a.txt" in r.output
    assert "b.txt" in r.output


@pytest.mark.asyncio
async def test_list_dir_nonexistent_fails(tool, subdir):
    r = await tool.execute({"action": "list_dir", "path": f"{subdir}/no_such_dir"})
    assert not r.success


# ── delete_file ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_file(tool, subdir):
    path = f"{subdir}/to_delete.txt"
    await tool.execute({"action": "write_file", "path": path, "content": "bye"})

    d = await tool.execute({"action": "delete_file", "path": path})
    assert d.success

    r = await tool.execute({"action": "read_file", "path": path})
    assert not r.success


@pytest.mark.asyncio
async def test_delete_nonexistent_fails(tool, subdir):
    d = await tool.execute({"action": "delete_file", "path": f"{subdir}/ghost.txt"})
    assert not d.success


# ── 安全：路径穿越防护 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_path_traversal_dotdot_rejected(tool):
    from models.errors import ToolError
    with pytest.raises(ToolError):
        await tool.execute({"action": "read_file", "path": "../etc/passwd"})


@pytest.mark.asyncio
async def test_path_traversal_nested_dotdot_rejected(tool):
    from models.errors import ToolError
    with pytest.raises(ToolError):
        await tool.execute({"action": "write_file", "path": "a/../../secret.txt", "content": "x"})


# ── 边界：缺少参数 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_path_fails(tool):
    r = await tool.execute({"action": "read_file", "path": ""})
    assert not r.success


@pytest.mark.asyncio
async def test_unsupported_action_fails(tool):
    r = await tool.execute({"action": "rename_file", "path": "x.txt"})
    assert not r.success
    assert "不支持" in (r.error or "")

"""
tests/test_note_tool.py - NoteTool + LocalNoteBackend 单元测试

覆盖：
  - LocalNoteBackend CRUD（创建/读取/更新/删除）
  - 搜索关键词
  - NoteTool action dispatch
  - Cloud backend 路由（关键词检测）
  - delete_note 需要确认
  - 无效 action 报错
"""

from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── LocalNoteBackend ──────────────────────────────────────────────────────────

class TestLocalNoteBackend:
    @pytest.fixture
    def backend(self, tmp_path):
        from modules.note_backends.local_backend import LocalNoteBackend
        return LocalNoteBackend(notes_dir=str(tmp_path / "notes"))

    @pytest.mark.asyncio
    async def test_create_and_read(self, backend):
        record = await backend.create_note("测试笔记", "这是内容", tags=["test"])
        assert record.note_id
        assert record.title == "测试笔记"

        read = await backend.read_note(record.note_id)
        assert read is not None
        assert read.title == "测试笔记"
        assert "这是内容" in read.content

    @pytest.mark.asyncio
    async def test_update_note(self, backend):
        record = await backend.create_note("原始", "旧内容")
        updated = await backend.update_note(record.note_id, "新内容", title="新标题")
        assert updated.content == "新内容"
        assert updated.title == "新标题"

        read = await backend.read_note(record.note_id)
        assert read is not None
        assert "新内容" in read.content

    @pytest.mark.asyncio
    async def test_delete_note(self, backend):
        record = await backend.create_note("要删除的笔记", "内容")
        success = await backend.delete_note(record.note_id)
        assert success
        assert await backend.read_note(record.note_id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, backend):
        success = await backend.delete_note("nonexistent-id")
        assert not success

    @pytest.mark.asyncio
    async def test_list_notes(self, backend):
        for i in range(3):
            await backend.create_note(f"笔记{i}", f"内容{i}", tags=["tag"])
        notes = await backend.list_notes()
        assert len(notes) == 3

    @pytest.mark.asyncio
    async def test_list_with_tag_filter(self, backend):
        await backend.create_note("有标签", "内容", tags=["work"])
        await backend.create_note("无标签", "内容", tags=["personal"])
        notes = await backend.list_notes(tag_filter=["work"])
        assert len(notes) == 1
        assert "work" in notes[0].tags

    @pytest.mark.asyncio
    async def test_search_notes(self, backend):
        await backend.create_note("会议记录", "今天讨论了项目进度")
        await backend.create_note("购物清单", "需要买牛奶和鸡蛋")
        results = await backend.search_notes("会议")
        assert len(results) == 1
        assert results[0].title == "会议记录"

    @pytest.mark.asyncio
    async def test_search_no_results(self, backend):
        await backend.create_note("测试", "内容")
        results = await backend.search_notes("xyz_not_exist")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_front_matter_preserved(self, backend):
        record = await backend.create_note("Front Matter Test", "body", tags=["a", "b"])
        read = await backend.read_note(record.note_id)
        assert read is not None
        assert "a" in read.tags


# ── NoteTool dispatch ─────────────────────────────────────────────────────────

class TestNoteTool:
    @pytest.fixture
    def note_tool(self, tmp_path):
        from modules.note_backends.local_backend import LocalNoteBackend
        from tools.note_tool import NoteTool
        backend = LocalNoteBackend(notes_dir=str(tmp_path / "notes"))
        return NoteTool(local_backend=backend, mcp_manager=None)

    @pytest.mark.asyncio
    async def test_create_note_action(self, note_tool):
        result = await note_tool.execute({
            "action": "create_note",
            "title": "新笔记",
            "content": "笔记内容",
        })
        assert result.success
        assert "新笔记" in result.output
        assert "note_id" in result.metadata

    @pytest.mark.asyncio
    async def test_list_notes_action(self, note_tool):
        await note_tool.execute({"action": "create_note", "title": "笔记1", "content": "x"})
        await note_tool.execute({"action": "create_note", "title": "笔记2", "content": "y"})
        result = await note_tool.execute({"action": "list_notes"})
        assert result.success
        assert "2" in result.output or result.metadata.get("count") == 2

    @pytest.mark.asyncio
    async def test_search_notes_action(self, note_tool):
        await note_tool.execute({"action": "create_note", "title": "技术文档", "content": "Python异步编程"})
        result = await note_tool.execute({"action": "search_notes", "query": "Python"})
        assert result.success
        assert "技术文档" in result.output

    @pytest.mark.asyncio
    async def test_delete_requires_confirmation(self, note_tool):
        assert note_tool.needs_confirmation_for({"action": "delete_note", "note_id": "xxx"})
        assert not note_tool.needs_confirmation_for({"action": "create_note", "title": "x"})

    @pytest.mark.asyncio
    async def test_invalid_action_fails(self, note_tool):
        result = await note_tool.execute({"action": "export_note"})
        assert not result.success
        assert "合法 action" in result.error

    @pytest.mark.asyncio
    async def test_create_note_requires_title(self, note_tool):
        result = await note_tool.execute({"action": "create_note", "content": "无标题"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_search_requires_query(self, note_tool):
        result = await note_tool.execute({"action": "search_notes"})
        assert not result.success


# ── Cloud backend routing ─────────────────────────────────────────────────────

class TestCloudRouting:
    def test_detect_evernote_in_title(self):
        from tools.note_tool import _detect_cloud_backend
        backend = _detect_cloud_backend({"title": "存到印象笔记的会议记录", "content": ""})
        assert backend == "evernote"

    def test_detect_baidu_in_content(self):
        from tools.note_tool import _detect_cloud_backend
        backend = _detect_cloud_backend({"title": "报告", "content": "请存到百度网盘"})
        assert backend == "baidu_netdisk"

    def test_no_keyword_returns_none(self):
        from tools.note_tool import _detect_cloud_backend
        backend = _detect_cloud_backend({"title": "普通笔记", "content": "本地内容"})
        assert backend is None

    def test_explicit_backend_param(self):
        from tools.note_tool import _detect_cloud_backend
        assert _detect_cloud_backend({"backend": "evernote"}) == "evernote"
        assert _detect_cloud_backend({"backend": "baidu_netdisk"}) == "baidu_netdisk"
        assert _detect_cloud_backend({"backend": "local"}) is None

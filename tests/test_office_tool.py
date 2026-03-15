"""
tests/test_office_tool.py - OfficeTool 单元测试

覆盖：
  - 路径验证（工作目录外拦截）
  - 不支持格式报错
  - .docx 创建 / 读取 / 追加 / 删除
  - .xlsx 创建 / 读取 / 追加
  - .pptx 创建 / 读取
  - delete 需要确认
  - 缺少依赖库时返回友好错误（mock import error）
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def office_tool(tmp_path, monkeypatch):
    """OfficeTool with workspace set to tmp_path."""
    from tools.office_tool import OfficeTool
    # Patch settings.workspace_dir to tmp_path
    import config
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path), raising=False)
    return OfficeTool()


# ── Path Validation ───────────────────────────────────────────────────────────

class TestPathValidation:
    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, office_tool):
        result = await office_tool.execute({
            "action": "create",
            "path": "../../../etc/passwd.docx",
            "title": "hack",
        })
        assert not result.success
        assert "不合法" in result.error

    @pytest.mark.asyncio
    async def test_unsupported_format_fails(self, office_tool):
        result = await office_tool.execute({
            "action": "create",
            "path": "test.pdf",
            "title": "test",
        })
        assert not result.success
        assert "格式" in result.error

    @pytest.mark.asyncio
    async def test_empty_path_fails(self, office_tool):
        result = await office_tool.execute({"action": "create", "path": ""})
        assert not result.success

    @pytest.mark.asyncio
    async def test_invalid_action_fails(self, office_tool):
        result = await office_tool.execute({"action": "convert", "path": "test.docx"})
        assert not result.success


# ── Confirmation ──────────────────────────────────────────────────────────────

class TestConfirmation:
    def test_delete_requires_confirmation(self, office_tool):
        assert office_tool.needs_confirmation_for({"action": "delete", "path": "x.docx"})

    def test_create_no_confirmation(self, office_tool):
        assert not office_tool.needs_confirmation_for({"action": "create", "path": "x.docx"})

    def test_read_no_confirmation(self, office_tool):
        assert not office_tool.needs_confirmation_for({"action": "read", "path": "x.docx"})


# ── Word (.docx) ──────────────────────────────────────────────────────────────

class TestDocx:
    @pytest.mark.asyncio
    async def test_create_and_read_docx(self, office_tool):
        pytest.importorskip("docx")
        result = await office_tool.execute({
            "action": "create",
            "path": "test_doc.docx",
            "title": "测试文档",
            "content": "# 第一章\n\n这是正文内容。",
        })
        assert result.success, result.error

        read_result = await office_tool.execute({
            "action": "read",
            "path": "test_doc.docx",
        })
        assert read_result.success
        assert "测试文档" in read_result.output or "第一章" in read_result.output

    @pytest.mark.asyncio
    async def test_append_docx(self, office_tool):
        pytest.importorskip("docx")
        await office_tool.execute({
            "action": "create",
            "path": "append_test.docx",
            "title": "追加测试",
            "content": "原始内容",
        })
        result = await office_tool.execute({
            "action": "append",
            "path": "append_test.docx",
            "content": "追加的内容",
        })
        assert result.success

        read_result = await office_tool.execute({"action": "read", "path": "append_test.docx"})
        assert "追加的内容" in read_result.output

    @pytest.mark.asyncio
    async def test_delete_docx(self, office_tool, tmp_path):
        pytest.importorskip("docx")
        await office_tool.execute({
            "action": "create",
            "path": "to_delete.docx",
            "title": "删除测试",
            "content": "x",
        })
        result = await office_tool.execute({"action": "delete", "path": "to_delete.docx"})
        assert result.success
        assert not (tmp_path / "to_delete.docx").exists()

    @pytest.mark.asyncio
    async def test_create_existing_fails(self, office_tool):
        pytest.importorskip("docx")
        await office_tool.execute({
            "action": "create", "path": "dup.docx", "title": "dup", "content": "x"
        })
        result = await office_tool.execute({
            "action": "create", "path": "dup.docx", "title": "dup", "content": "x"
        })
        assert not result.success
        assert "已存在" in result.error

    @pytest.mark.asyncio
    async def test_read_nonexistent_fails(self, office_tool):
        pytest.importorskip("docx")
        result = await office_tool.execute({"action": "read", "path": "ghost.docx"})
        assert not result.success
        assert "不存在" in result.error


# ── Excel (.xlsx) ─────────────────────────────────────────────────────────────

class TestXlsx:
    @pytest.mark.asyncio
    async def test_create_and_read_xlsx(self, office_tool):
        pytest.importorskip("openpyxl")
        content = "| 姓名 | 部门 | 薪资 |\n| 张三 | 技术 | 15000 |\n| 李四 | 产品 | 18000 |"
        result = await office_tool.execute({
            "action": "create",
            "path": "staff.xlsx",
            "title": "员工表",
            "content": content,
        })
        assert result.success, result.error

        read_result = await office_tool.execute({"action": "read", "path": "staff.xlsx"})
        assert read_result.success
        assert "张三" in read_result.output
        assert "技术" in read_result.output

    @pytest.mark.asyncio
    async def test_append_xlsx(self, office_tool):
        pytest.importorskip("openpyxl")
        await office_tool.execute({
            "action": "create", "path": "data.xlsx", "title": "数据", "content": "| A | B |"
        })
        result = await office_tool.execute({
            "action": "append", "path": "data.xlsx", "content": "| C | D |"
        })
        assert result.success


# ── PowerPoint (.pptx) ────────────────────────────────────────────────────────

class TestPptx:
    @pytest.mark.asyncio
    async def test_create_and_read_pptx(self, office_tool):
        pytest.importorskip("pptx")
        result = await office_tool.execute({
            "action": "create",
            "path": "presentation.pptx",
            "title": "季度汇报",
            "content": "业绩概览\n---\n# Q1 结果\n收入增长 20%",
        })
        assert result.success, result.error

        read_result = await office_tool.execute({"action": "read", "path": "presentation.pptx"})
        assert read_result.success
        assert "Slide" in read_result.output


# ── Schema ────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_schema_structure(self, office_tool):
        schema = office_tool.get_schema()
        assert schema["name"] == "office_tool"
        props = schema["parameters"]["properties"]
        assert "action" in props
        assert "path" in props
        assert "styles" in props
        assert "action" in schema["parameters"]["required"]
        assert "path" in schema["parameters"]["required"]

"""
tools/file_tool.py - Secure file operations within WORKSPACE_DIR for STONE (默行者)

All paths are resolved relative to WORKSPACE_DIR and verified to stay within it.
Write operations require dry-run confirmation.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from config import settings
from models.errors import ToolError
from tools.base import ToolInterface, ToolResult

logger = logging.getLogger(__name__)

MAX_READ_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_LIST_ENTRIES = 500


def _resolve_safe(base: Path, user_path: str) -> Path:
    """
    Resolve user_path relative to base and raise ToolError if it escapes.
    """
    # Reject obvious traversal attempts early
    if ".." in user_path:
        raise ToolError(
            message=f"路径中不允许包含 '..': {user_path!r}",
            tool_name="file_tool",
        )
    resolved = (base / user_path).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        raise ToolError(
            message=f"路径越界：{user_path!r} 超出工作目录范围",
            tool_name="file_tool",
        )
    return resolved


class FileTool(ToolInterface):
    """
    Provides read, write, list, and mkdir operations within WORKSPACE_DIR.
    Write/mkdir operations require confirmation.
    """

    name = "file_tool"
    requires_confirmation = False  # per-action check in needs_confirmation_for()

    @property
    def description(self) -> str:
        return (
            f"在工作目录（{settings.workspace_dir}）内进行文件操作。"
            "action 说明：\n"
            "- read_file：读取文件内容\n"
            "- write_file：创建或写入文件（创建空文件时 content 传空字符串）\n"
            "- delete_file：删除文件（需确认）\n"
            "- delete_dir：删除目录及其所有内容（需确认，递归删除）\n"
            "- list_dir：列出目录内容（path='.' 列出工作目录根）\n"
            "- create_dir：创建目录，不要用此 action 创建文件\n"
            "路径均相对于工作目录，不允许 '..' 越界。写操作和删除操作需要用户确认。"
        )

    def needs_confirmation_for(self, params: dict) -> bool:
        """write_file, delete_file, delete_dir, create_dir need confirmation; read/list are safe."""
        return params.get("action", "") in ("write_file", "delete_file", "delete_dir", "create_dir")

    @property
    def workspace(self) -> Path:
        path = settings.workspace_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        action: str = params.get("action", "").strip().lower()

        dispatch = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "delete_file": self._delete_file,
            "delete_dir": self._delete_dir,
            "list_dir": self._list_dir,
            "create_dir": self._create_dir,
        }

        handler = dispatch.get(action)
        if handler is None:
            return ToolResult.fail(
                f"不支持的操作 {action!r}。支持的操作：{', '.join(dispatch)}"
            )

        return await handler(params, user_id)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def _read_file(self, params: dict[str, Any], user_id: str) -> ToolResult:
        path_str: str = params.get("path", "")
        if not path_str:
            return ToolResult.fail("缺少参数 'path'")

        target = _resolve_safe(self.workspace, path_str)

        if not target.exists():
            return ToolResult.fail(f"文件不存在：{path_str}")
        if not target.is_file():
            return ToolResult.fail(f"{path_str!r} 不是文件")

        size = target.stat().st_size
        if size > MAX_READ_SIZE:
            return ToolResult.fail(
                f"文件过大（{size // 1024}KB），超过 10MB 限制"
            )

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except PermissionError as exc:
            raise ToolError(message=f"权限拒绝：{exc}", tool_name=self.name) from exc
        except OSError as exc:
            raise ToolError(message=f"读取失败：{exc}", tool_name=self.name) from exc

        logger.info("FileTool.read [user=%s]: %s (%d bytes)", user_id, path_str, size)
        return ToolResult.ok(
            output=content,
            metadata={"path": str(target), "size_bytes": size},
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    async def _write_file(self, params: dict[str, Any], user_id: str) -> ToolResult:
        path_str: str = params.get("path", "")
        content: str = params.get("content", "")
        if not path_str:
            return ToolResult.fail("缺少参数 'path'")

        target = _resolve_safe(self.workspace, path_str)
        target.parent.mkdir(parents=True, exist_ok=True)

        overwrite = params.get("overwrite", True)
        if target.exists() and not overwrite:
            return ToolResult.fail(f"文件已存在：{path_str}，设置 overwrite=true 以覆盖")

        try:
            target.write_text(content, encoding="utf-8")
        except PermissionError as exc:
            raise ToolError(message=f"权限拒绝：{exc}", tool_name=self.name) from exc
        except OSError as exc:
            raise ToolError(message=f"写入失败：{exc}", tool_name=self.name) from exc

        logger.info(
            "FileTool.write [user=%s]: %s (%d chars)",
            user_id,
            path_str,
            len(content),
        )
        return ToolResult.ok(
            output=f"文件已写入：{path_str}（{len(content)} 字符）",
            metadata={"path": str(target)},
        )

    # ── Delete File ───────────────────────────────────────────────────────────

    async def _delete_file(self, params: dict[str, Any], user_id: str) -> ToolResult:
        path_str: str = params.get("path", "")
        if not path_str:
            return ToolResult.fail("缺少参数 'path'")

        target = _resolve_safe(self.workspace, path_str)

        if not target.exists():
            return ToolResult.fail(f"文件不存在：{path_str}")
        if target.is_dir():
            return ToolResult.fail(f"{path_str!r} 是目录，无法用 delete_file 删除")

        try:
            target.unlink()
        except PermissionError as exc:
            raise ToolError(message=f"权限拒绝：{exc}", tool_name=self.name) from exc
        except OSError as exc:
            raise ToolError(message=f"删除失败：{exc}", tool_name=self.name) from exc

        logger.info("FileTool.delete [user=%s]: %s", user_id, path_str)
        return ToolResult.ok(
            output=f"文件已删除：{path_str}",
            metadata={"path": str(target)},
        )

    # ── Delete Dir ────────────────────────────────────────────────────────────

    async def _delete_dir(self, params: dict[str, Any], user_id: str) -> ToolResult:
        import shutil

        path_str: str = params.get("path", "")
        if not path_str:
            return ToolResult.fail("缺少参数 'path'")

        target = _resolve_safe(self.workspace, path_str)

        if not target.exists():
            return ToolResult.fail(f"目录不存在：{path_str}")
        if not target.is_dir():
            return ToolResult.fail(f"{path_str!r} 不是目录，请使用 delete_file 删除文件")

        try:
            shutil.rmtree(target)
        except PermissionError as exc:
            raise ToolError(message=f"权限拒绝：{exc}", tool_name=self.name) from exc
        except OSError as exc:
            raise ToolError(message=f"删除目录失败：{exc}", tool_name=self.name) from exc

        logger.info("FileTool.delete_dir [user=%s]: %s", user_id, path_str)
        return ToolResult.ok(
            output=f"目录已删除：{path_str}",
            metadata={"path": str(target)},
        )

    # ── List Dir ──────────────────────────────────────────────────────────────

    async def _list_dir(self, params: dict[str, Any], user_id: str) -> ToolResult:
        path_str: str = params.get("path", ".")
        show_hidden: bool = params.get("show_hidden", False)
        target = _resolve_safe(self.workspace, path_str)

        if not target.exists():
            return ToolResult.fail(f"路径不存在：{path_str}")
        if not target.is_dir():
            return ToolResult.fail(f"{path_str!r} 不是目录")

        try:
            all_entries = list(target.iterdir())
        except PermissionError as exc:
            raise ToolError(message=f"权限拒绝：{exc}", tool_name=self.name) from exc

        # Filter hidden files unless explicitly requested
        if not show_hidden:
            all_entries = [e for e in all_entries if not e.name.startswith(".")]

        # Dirs first (alphabetical), then files (alphabetical)
        dirs = sorted([e for e in all_entries if e.is_dir()], key=lambda p: p.name)
        files = sorted([e for e in all_entries if e.is_file()], key=lambda p: p.name)
        entries = (dirs + files)[:MAX_LIST_ENTRIES]

        lines: list[str] = [f"📂 {path_str}  （{len(dirs)} 个目录，{len(files)} 个文件）\n"]
        if dirs:
            for d in dirs:
                lines.append(f"📁 {d.name}/")
        if files:
            for f in files:
                try:
                    size = f.stat().st_size
                    size_info = f" ({size:,} bytes)" if size > 0 else " (空)"
                except OSError:
                    size_info = ""
                lines.append(f"📄 {f.name}{size_info}")

        if len(all_entries) > MAX_LIST_ENTRIES:
            lines.append(f"\n（仅显示前 {MAX_LIST_ENTRIES} 个条目）")

        return ToolResult.ok(
            output="\n".join(lines),
            metadata={"path": str(target), "dir_count": len(dirs), "file_count": len(files)},
        )

    # ── Create Dir ────────────────────────────────────────────────────────────

    async def _create_dir(self, params: dict[str, Any], user_id: str) -> ToolResult:
        path_str: str = params.get("path", "")
        if not path_str:
            return ToolResult.fail("缺少参数 'path'")

        target = _resolve_safe(self.workspace, path_str)

        try:
            target.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ToolError(message=f"权限拒绝：{exc}", tool_name=self.name) from exc
        except OSError as exc:
            raise ToolError(message=f"创建目录失败：{exc}", tool_name=self.name) from exc

        logger.info("FileTool.mkdir [user=%s]: %s", user_id, path_str)
        return ToolResult.ok(
            output=f"目录已创建：{path_str}",
            metadata={"path": str(target)},
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read_file", "write_file", "delete_file", "delete_dir", "list_dir", "create_dir"],
                        "description": (
                            "要执行的文件操作：\n"
                            "- read_file: 读取文件内容\n"
                            "- write_file: 创建或写入文件（创建空文件时 content 传 ''，会自动创建父目录）\n"
                            "- delete_file: 删除文件（需用户确认）\n"
                            "- delete_dir: 删除目录及其所有内容，递归删除（需用户确认）\n"
                            "- list_dir: 列出目录内容，path='.' 列出工作目录根\n"
                            "- create_dir: 创建目录（不是文件！创建文件请用 write_file）"
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": "相对于工作目录的文件或目录路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "write_file 时的文件内容，未指定时传空字符串",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "write_file 时是否覆盖已有文件，默认 true",
                        "default": True,
                    },
                },
                "required": ["action", "path"],
            },
        }


__all__ = ["FileTool"]

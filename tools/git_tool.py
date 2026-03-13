"""
tools/git_tool.py - Git operations tool for STONE (默行者)

Phase 1a: read-only operations (status, log, diff) - no confirmation needed.
Phase 1b: write operations (commit, push) - requires confirmation + Docker sandbox.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import settings
from models.errors import ToolError
from tools.base import ToolInterface, ToolResult

logger = logging.getLogger(__name__)


class GitTool(ToolInterface):
    """
    Provides git read operations in Phase 1a.
    Write operations (commit, push) are stubbed for Phase 1b.
    """

    name = "git_tool"
    description = (
        "执行 git 操作。Phase 1a 支持只读操作（status、log、diff）。"
        "commit 和 push 在 Phase 1b 实现（需要确认）。"
    )
    requires_confirmation = False  # read-only by default; toggled for write ops

    @property
    def repo_base(self) -> Path:
        return settings.workspace_dir

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        action: str = params.get("action", "").strip().lower()

        read_ops = {
            "status": self._git_status,
            "log": self._git_log,
            "diff": self._git_diff,
        }
        write_ops = {"commit", "push", "add", "checkout", "branch", "merge"}

        if action in write_ops:
            return ToolResult.fail(
                f"git {action} 操作尚未实现（Phase 1b）。当前仅支持：status、log、diff"
            )

        handler = read_ops.get(action)
        if handler is None:
            return ToolResult.fail(
                f"不支持的 git 操作 {action!r}。支持：{', '.join(read_ops)}"
            )

        return await handler(params, user_id)

    # ── Read Operations ───────────────────────────────────────────────────────

    async def _git_status(self, params: dict[str, Any], user_id: str) -> ToolResult:
        repo_path = self._get_repo_path(params)
        return await self._run_git(["status", "--short", "--branch"], repo_path)

    async def _git_log(self, params: dict[str, Any], user_id: str) -> ToolResult:
        n = int(params.get("n", 10))
        n = min(n, 50)  # cap to 50 entries
        repo_path = self._get_repo_path(params)
        return await self._run_git(
            ["log", f"--oneline", f"-{n}", "--no-color"],
            repo_path,
        )

    async def _git_diff(self, params: dict[str, Any], user_id: str) -> ToolResult:
        repo_path = self._get_repo_path(params)
        ref = params.get("ref", "")
        cmd = ["diff", "--no-color"]
        if ref:
            cmd.append(ref)
        return await self._run_git(cmd, repo_path)

    # ── TODO: Phase 1b Write Operations ──────────────────────────────────────

    # TODO: Phase 1b - implement git add
    # async def _git_add(self, params, user_id): ...

    # TODO: Phase 1b - implement git commit (requires confirmation)
    # Requires: dry_run confirmation, user identity config
    # async def _git_commit(self, params, user_id): ...

    # TODO: Phase 1b - implement git push (requires confirmation + sandbox check)
    # async def _git_push(self, params, user_id): ...

    # TODO: Phase 1b - implement git checkout
    # async def _git_checkout(self, params, user_id): ...

    # TODO: Phase 1b - implement git branch
    # async def _git_branch(self, params, user_id): ...

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_repo_path(self, params: dict[str, Any]) -> Path:
        repo_rel = params.get("repo", ".")
        if ".." in repo_rel:
            raise ToolError(
                message="路径中不允许包含 '..'",
                tool_name=self.name,
            )
        path = (self.repo_base / repo_rel).resolve()
        try:
            path.relative_to(self.repo_base.resolve())
        except ValueError:
            raise ToolError(
                message=f"路径越界：{repo_rel!r}",
                tool_name=self.name,
            )
        return path

    async def _run_git(self, args: list[str], cwd: Path) -> ToolResult:
        import asyncio

        if not (cwd / ".git").exists():
            return ToolResult.fail(f"{cwd} 不是 git 仓库")

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            raise ToolError(message="git 命令超时", tool_name=self.name)
        except FileNotFoundError:
            raise ToolError(message="git 未安装", tool_name=self.name)
        except Exception as exc:
            raise ToolError(message=f"git 执行失败：{exc}", tool_name=self.name) from exc

        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()

        if proc.returncode != 0:
            return ToolResult.fail(error=err or f"git 返回码 {proc.returncode}")

        return ToolResult.ok(output=out or "(无输出)", metadata={"cwd": str(cwd)})

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "log", "diff"],
                        "description": "git 操作类型（Phase 1a 仅支持只读操作）",
                    },
                    "repo": {
                        "type": "string",
                        "description": "相对于工作目录的 git 仓库路径，默认 '.'",
                        "default": ".",
                    },
                    "n": {
                        "type": "integer",
                        "description": "log 操作显示的提交数量，默认 10",
                        "default": 10,
                    },
                    "ref": {
                        "type": "string",
                        "description": "diff 操作的比较引用（分支名、commit hash 等）",
                    },
                },
                "required": ["action"],
            },
        }


__all__ = ["GitTool"]

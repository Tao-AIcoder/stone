"""
tools/code_tool.py - Sandboxed code execution tool skeleton for STONE (默行者)

TODO: Phase 1b - implement code execution via Docker sandbox.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import ToolInterface, ToolResult

logger = logging.getLogger(__name__)


class CodeTool(ToolInterface):
    """
    Executes code snippets inside a Docker sandbox container.

    TODO: Phase 1b - implement the following:
    - Spin up ephemeral Docker container from DOCKER_SANDBOX_IMAGE
    - Mount workspace volume (read-only by default)
    - Execute code with timeout (default 60s)
    - Capture stdout / stderr
    - Kill container after execution
    - Resource limits: 256MB RAM, 1 CPU core
    - Supported languages: python3, bash (via sandbox)
    - Block network access inside sandbox
    - Always requires dry-run confirmation before execution
    - Integration with modules/sandbox/docker.py

    Note: Even in Phase 1b, this tool MUST go through DryRunManager.
    Code execution is inherently destructive and requires explicit confirmation.
    """

    name = "code_tool"
    description = (
        "在隔离的 Docker 沙盒中执行代码（Python、Bash）并返回输出。"
        "【Phase 1b 功能，需要 Docker，当前不可用】"
    )
    requires_confirmation = True

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        # TODO: Phase 1b - implement Docker-based code execution
        return ToolResult.fail(
            "code_tool 尚未实现（Phase 1b）。"
            "需要 Docker 沙盒支持。计划支持 Python 和 Bash 代码执行。"
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["python", "bash"],
                        "description": "编程语言",
                        "default": "python",
                    },
                    "code": {
                        "type": "string",
                        "description": "要执行的代码",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "执行超时秒数，默认 60",
                        "default": 60,
                    },
                },
                "required": ["code"],
            },
        }


__all__ = ["CodeTool"]

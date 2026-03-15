"""
registry/skill_registry.py - Tool / skill registry for STONE (默行者)

Maintains a catalogue of registered tools, provides lookup by name,
and generates the JSON Schema list used by the LLM for tool calling.
"""

from __future__ import annotations

import logging
from typing import Any

from models.errors import ModuleNotFoundError
from models.skill import Skill, SkillCategory, SkillParameter
from tools.base import ToolInterface

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Central registry for all STONE tools / skills.

    Tools are registered as (Skill metadata, ToolInterface instance) pairs.
    The registry is queried by the agent to:
    1. Get tool schemas for LLM prompting
    2. Retrieve tool instances for execution
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolInterface] = {}          # name -> instance
        self._skills: dict[str, Skill] = {}                 # name -> metadata

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, tool: ToolInterface, skill_meta: Skill | None = None) -> None:
        """Register a tool instance and optional skill metadata."""
        name = tool.name
        if not name:
            raise ValueError("Tool must have a non-empty name attribute")

        self._tools[name] = tool

        if skill_meta is not None:
            self._skills[name] = skill_meta
        else:
            # Auto-generate minimal Skill from tool attributes
            self._skills[name] = Skill(
                name=name,
                display_name=name.replace("_", " ").title(),
                description=tool.description,
                requires_confirmation=tool.requires_confirmation,
                enabled=True,
            )

        logger.debug("SkillRegistry: registered tool %r", name)

    def register_phase1a_tools(self) -> None:
        """Register all Phase 1a tools with their metadata."""
        from tools.bash_tool import BashTool, SAFE_COMMANDS
        from tools.search_tool import SearchTool
        from tools.file_tool import FileTool
        from tools.git_tool import GitTool
        from tools.note_tool import NoteTool
        from tools.http_tool import HttpTool
        from tools.code_tool import CodeTool
        from tools.office_tool import OfficeTool
        from modules.note_backends.local_backend import LocalNoteBackend

        # bash_tool
        self.register(
            BashTool(),
            Skill(
                name="bash_tool",
                display_name="Bash 命令执行",
                description=(
                    "在服务器上执行安全的系统命令。"
                    f"支持命令：{', '.join(sorted(SAFE_COMMANDS))}"
                ),
                category=SkillCategory.SYSTEM,
                requires_confirmation=False,
                phase="1a",
                parameters=[
                    SkillParameter(
                        name="command",
                        type="string",
                        description="要执行的 shell 命令（仅白名单命令）",
                        required=True,
                    )
                ],
                tags=["system", "shell", "read"],
            ),
        )

        # search_tool
        self.register(
            SearchTool(),
            Skill(
                name="search_tool",
                display_name="网络搜索",
                description="使用 Tavily API 搜索互联网信息，返回最多 5 条结果。",
                category=SkillCategory.SEARCH,
                requires_confirmation=False,
                phase="1a",
                parameters=[
                    SkillParameter(
                        name="query",
                        type="string",
                        description="搜索关键词或问题",
                        required=True,
                    ),
                    SkillParameter(
                        name="max_results",
                        type="integer",
                        description="返回结果数量（默认 5）",
                        required=False,
                        default=5,
                    ),
                ],
                tags=["search", "web", "read"],
            ),
        )

        # file_tool
        self.register(
            FileTool(),
            Skill(
                name="file_tool",
                display_name="文件操作",
                description=(
                    "在工作目录内读写文件、列出目录、创建目录。"
                    "写操作需要用户确认。"
                ),
                category=SkillCategory.FILE,
                requires_confirmation=True,
                phase="1a",
                parameters=[
                    SkillParameter(
                        name="action",
                        type="string",
                        description="操作类型：read_file | write_file | list_dir | create_dir",
                        required=True,
                        enum_values=["read_file", "write_file", "list_dir", "create_dir"],
                    ),
                    SkillParameter(
                        name="path",
                        type="string",
                        description="相对于工作目录的路径",
                        required=True,
                    ),
                    SkillParameter(
                        name="content",
                        type="string",
                        description="write_file 时的文件内容",
                        required=False,
                        default="",
                    ),
                ],
                tags=["file", "read", "write"],
            ),
        )

        # Phase 1b tools
        for stub_tool, category in [
            (GitTool(), SkillCategory.GIT),
            (NoteTool(local_backend=LocalNoteBackend()), SkillCategory.NOTE),
            (HttpTool(), SkillCategory.HTTP),
            (CodeTool(), SkillCategory.CODE),
            (OfficeTool(), SkillCategory.FILE),
        ]:
            self.register(
                stub_tool,
                Skill(
                    name=stub_tool.name,
                    display_name=stub_tool.name.replace("_", " ").title(),
                    description=stub_tool.description,
                    category=category,
                    requires_confirmation=stub_tool.requires_confirmation,
                    enabled=True,   # visible but returns not-implemented
                    phase="1b",
                ),
            )

        logger.info(
            "SkillRegistry: %d tools registered (Phase 1a active + Phase 1b stubs)",
            len(self._tools),
        )

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get_tool(self, name: str) -> Skill | None:
        """Return Skill metadata for a tool name, or None if not found."""
        return self._skills.get(name)

    def get_tool_instance(self, name: str) -> ToolInterface | None:
        """Return the ToolInterface instance for a tool name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Skill]:
        """Return all registered skills (metadata only)."""
        return list(self._skills.values())

    def list_enabled_tools(self) -> list[Skill]:
        """Return only enabled skills."""
        return [s for s in self._skills.values() if s.enabled]

    # ── Schema for LLM ───────────────────────────────────────────────────────

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """
        Return the JSON Schema list for all enabled tools, suitable for
        passing to an LLM as the 'tools' parameter.
        """
        schemas = []
        for name, tool in self._tools.items():
            skill = self._skills.get(name)
            if skill and not skill.enabled:
                continue
            schemas.append(tool.get_schema())
        return schemas

    def get_tools_prompt_summary(self) -> str:
        """
        Return a brief text summary of available tools for inclusion in
        system prompts (alternative to full JSON schema).
        """
        lines = ["可用工具列表："]
        for skill in self.list_enabled_tools():
            phase_tag = "" if skill.phase == "1a" else f" [Phase {skill.phase}]"
            conf_tag = " ⚠️需确认" if skill.requires_confirmation else ""
            lines.append(
                f"- {skill.name}: {skill.description[:80]}{phase_tag}{conf_tag}"
            )
        return "\n".join(lines)


__all__ = ["SkillRegistry"]

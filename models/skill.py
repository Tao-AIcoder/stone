"""
models/skill.py - Skill / tool metadata models for STONE (默行者)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SkillCategory(str, Enum):
    """High-level category for grouping skills in the registry."""

    SYSTEM = "system"          # OS / bash operations
    FILE = "file"              # File read/write operations
    SEARCH = "search"          # Web / local search
    CODE = "code"              # Code execution / analysis
    GIT = "git"                # Version control
    NOTE = "note"              # Note-taking / knowledge base
    HTTP = "http"              # External HTTP requests
    SCHEDULE = "schedule"      # Task scheduling
    MEMORY = "memory"          # Memory read/write
    MISC = "misc"              # Uncategorized


class SkillParameter(BaseModel):
    """JSON Schema-compatible parameter descriptor."""

    name: str
    type: str                   # "string" | "integer" | "boolean" | "array" | "object"
    description: str = ""
    required: bool = True
    default: Any = None
    enum_values: list[Any] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    def to_json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum_values:
            schema["enum"] = self.enum_values
        if self.default is not None:
            schema["default"] = self.default
        return schema


class Skill(BaseModel):
    """Metadata record for a registered skill / tool."""

    name: str                   # Unique identifier used when calling the tool
    display_name: str = ""
    description: str = ""
    category: SkillCategory = SkillCategory.MISC

    enabled: bool = True
    requires_confirmation: bool = False
    phase: str = "1a"           # "1a" | "1b" | "2" | "3"

    parameters: list[SkillParameter] = Field(default_factory=list)

    # Optional: tags for model routing hints
    tags: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    def to_tool_schema(self) -> dict[str, Any]:
        """
        Emit the JSON Schema fragment that can be passed to an LLM as a
        tool/function definition.
        """
        properties: dict[str, Any] = {}
        required_params: list[str] = []

        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required_params.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required_params,
            },
        }


__all__ = [
    "SkillCategory",
    "SkillParameter",
    "Skill",
]

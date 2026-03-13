"""
config.py - Central configuration for STONE (默行者)

Reads all settings from environment variables and stone.config.json.
Uses pydantic-settings for env var management and a singleton pattern.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_CONFIG_FILE = Path(__file__).parent / "stone.config.json"


class StoneSettings(BaseSettings):
    """All runtime configuration for the STONE system."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── API Keys ──────────────────────────────────────────────────────────────
    zhipuai_api_key: str = Field(default="", description="智谱 AI API key")
    dashscope_api_key: str = Field(default="", description="阿里云通义 API key")
    tavily_api_key: str = Field(default="", description="Tavily search API key")

    # ── Feishu / Lark ─────────────────────────────────────────────────────────
    feishu_app_id: str = Field(default="", description="Feishu App ID")
    feishu_app_secret: str = Field(default="", description="Feishu App Secret")

    # ── Admin / Security ──────────────────────────────────────────────────────
    admin_whitelist: list[str] = Field(
        default_factory=list,
        description="Comma-separated Feishu open_ids allowed to chat",
    )
    admin_pin: str = Field(default="", description="bcrypt hash of admin PIN")
    totp_secret: str = Field(default="", description="BASE32 TOTP secret")

    # ── Paths ─────────────────────────────────────────────────────────────────
    workspace_dir: Path = Field(
        default=Path("/tmp/stone-workspace"),
        description="Sandbox workspace directory",
    )
    notes_dir: Path = Field(
        default=Path("/tmp/stone-notes"),
        description="Notes directory",
    )
    db_path: Path = Field(
        default=Path("stone.db"),
        description="SQLite database path",
    )

    # ── Model / Ollama ────────────────────────────────────────────────────────
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL",
    )
    docker_sandbox_image: str = Field(
        default="python:3.11-slim",
        description="Docker image used for sandboxed code execution",
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="Python logging level")

    # ── Derived from stone.config.json ───────────────────────────────────────
    stone_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Parsed stone.config.json content",
    )

    @field_validator("admin_whitelist", mode="before")
    @classmethod
    def parse_whitelist(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return []

    @field_validator("workspace_dir", "notes_dir", "db_path", mode="before")
    @classmethod
    def coerce_path(cls, v: Any) -> Path:
        return Path(v)

    def model_post_init(self, __context: Any) -> None:  # noqa: ANN401
        """Load stone.config.json after env vars are parsed."""
        if _CONFIG_FILE.exists():
            try:
                data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
                object.__setattr__(self, "stone_config", data)
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to load stone.config.json: %s", exc)

    # ── Convenience accessors ─────────────────────────────────────────────────

    @property
    def agent_config(self) -> dict[str, Any]:
        return self.stone_config.get("agent", {})

    @property
    def dry_run_enabled(self) -> bool:
        return bool(self.agent_config.get("dry_run", True))

    @property
    def context_window(self) -> int:
        return int(self.agent_config.get("context_window", 20))

    @property
    def default_model(self) -> str:
        router = self.stone_config.get("modules", {}).get("model_router", {})
        return router.get("default_model", "qwen2.5:14b")

    @property
    def privacy_mode(self) -> str:
        router = self.stone_config.get("modules", {}).get("model_router", {})
        return router.get("privacy_mode", "balanced")

    @property
    def cloud_models(self) -> list[dict[str, Any]]:
        return (
            self.stone_config.get("modules", {})
            .get("models", {})
            .get("cloud", [])
        )

    @property
    def local_models(self) -> list[dict[str, Any]]:
        return (
            self.stone_config.get("modules", {})
            .get("models", {})
            .get("local", [])
        )

    def redacted_repr(self) -> str:
        """Return a string representation with sensitive fields masked."""
        safe = {
            "feishu_app_id": self.feishu_app_id,
            "admin_whitelist": self.admin_whitelist,
            "ollama_base_url": self.ollama_base_url,
            "log_level": self.log_level,
            "workspace_dir": str(self.workspace_dir),
            "notes_dir": str(self.notes_dir),
            "zhipuai_api_key": "***" if self.zhipuai_api_key else "(unset)",
            "dashscope_api_key": "***" if self.dashscope_api_key else "(unset)",
            "tavily_api_key": "***" if self.tavily_api_key else "(unset)",
            "feishu_app_secret": "***" if self.feishu_app_secret else "(unset)",
            "admin_pin": "***" if self.admin_pin else "(unset)",
            "totp_secret": "***" if self.totp_secret else "(unset)",
        }
        return str(safe)


@lru_cache(maxsize=1)
def get_settings() -> StoneSettings:
    """Return the singleton StoneSettings instance."""
    settings = StoneSettings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.info("STONE settings loaded: %s", settings.redacted_repr())
    return settings


# Convenience alias used throughout the codebase
settings = get_settings()
DEFAULT_USER_ID = "default_user"

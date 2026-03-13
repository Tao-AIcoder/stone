"""
modules/sandbox/docker.py - Docker sandbox (Phase 1b, stub).

Full implementation planned for Phase 1b.
Security properties when implemented:
  - network_mode=none      (no outbound connections)
  - read-only filesystem
  - user=nobody inside container
  - cap-drop=ALL
  - CPU/memory hard limits

To activate: install docker SDK, set modules.sandbox.driver = "docker" in stone.config.json.
"""

from __future__ import annotations

import logging
from typing import Any

from modules.interfaces.sandbox import SandboxInterface, SandboxResult

logger = logging.getLogger(__name__)


class DockerSandboxConfig:
    image: str = "python:3.11-slim"
    memory_limit: str = "256m"
    cpu_quota: int = 50000       # 50% of one CPU
    network_mode: str = "none"
    timeout_seconds: int = 60
    workspace_mount: str = "/workspace"
    read_only_workspace: bool = True


class DockerSandbox(SandboxInterface):
    """
    Docker-based isolated execution sandbox.

    Phase 1b stub — all methods return a failure result until implemented.
    Switch stone.config.json  modules.sandbox.driver = "docker"  once done.
    """

    def __init__(self) -> None:
        self.config = DockerSandboxConfig()
        self._docker_client: Any = None

    async def initialize(self) -> None:
        """Try to connect to Docker daemon (non-fatal if unavailable)."""
        try:
            import docker  # type: ignore[import]
            self._docker_client = docker.from_env()
            self._docker_client.ping()
            logger.info("DockerSandbox: Docker daemon connected")
        except Exception as exc:
            logger.warning("DockerSandbox: Docker not available (%s) — use noop sandbox", exc)

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """TODO Phase 1b: run code inside an ephemeral container."""
        return SandboxResult(
            exit_code=1,
            stderr="DockerSandbox not yet implemented (Phase 1b)",
        )

    async def run_bash(
        self,
        command: str,
        timeout: int = 30,
    ) -> SandboxResult:
        """TODO Phase 1b: run shell command inside an ephemeral container."""
        return SandboxResult(
            exit_code=1,
            stderr="DockerSandbox not yet implemented (Phase 1b)",
        )

    async def close(self) -> None:
        if self._docker_client is not None:
            try:
                self._docker_client.close()
            except Exception:
                pass


__all__ = ["DockerSandbox", "DockerSandboxConfig"]

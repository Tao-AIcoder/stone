"""
modules/sandbox/docker.py - Docker sandbox module skeleton for STONE (默行者)

TODO: Phase 1b - implement Docker-based sandboxed execution.

This file defines the interface and configuration. Full implementation
requires the docker SDK and is planned for Phase 1b.
"""

from __future__ import annotations

import logging
from typing import Any

from modules.base import HealthStatus, ModuleHealth, StoneModule

logger = logging.getLogger(__name__)


class DockerSandboxConfig:
    """Configuration for the Docker sandbox."""

    image: str = "python:3.11-slim"
    memory_limit: str = "256m"
    cpu_quota: int = 50000       # 50% of one CPU
    network_mode: str = "none"   # No network access
    timeout_seconds: int = 60
    workspace_mount: str = "/workspace"
    read_only_workspace: bool = True


class SandboxResult:
    """Result of a sandboxed execution."""

    def __init__(
        self,
        exit_code: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class DockerSandbox(StoneModule):
    """
    Docker-based code execution sandbox.

    TODO: Phase 1b - implement the following:
    1. Verify Docker daemon is running on initialize()
    2. Pull sandbox image if not present
    3. execute(code, language, user_id) -> SandboxResult:
       - Create ephemeral container with resource limits
       - Copy code into container
       - Run with timeout
       - Capture stdout/stderr
       - Always remove container after execution (rm=True)
    4. Health check: ping Docker daemon
    5. Image management: pull, verify, list available images

    Security notes:
    - network_mode="none" prevents outbound connections
    - read-only filesystem by default
    - user=nobody inside container
    - No /proc, /sys, /dev mount propagation
    - cap-drop=ALL
    """

    module_name = "sandbox.docker"

    def __init__(self) -> None:
        self.config = DockerSandboxConfig()
        self._docker_client: Any = None

    async def initialize(self) -> None:
        """
        TODO: Phase 1b - connect to Docker daemon and verify image.

        try:
            import docker
            self._docker_client = docker.from_env()
            self._docker_client.ping()
            logger.info("Docker daemon connected")
        except Exception as exc:
            logger.warning("Docker not available: %s", exc)
            # Non-fatal in Phase 1a - code_tool will return not-implemented
        """
        logger.info("DockerSandbox: Phase 1b stub - Docker not initialized")

    async def shutdown(self) -> None:
        """TODO: Phase 1b - close Docker client."""
        if self._docker_client is not None:
            try:
                self._docker_client.close()
            except Exception:
                pass

    async def health_check(self) -> ModuleHealth:
        """Check if Docker daemon is reachable."""
        if self._docker_client is None:
            return ModuleHealth(
                module_name=self.module_name,
                status=HealthStatus.UNKNOWN,
                message="Docker not initialized (Phase 1b)",
            )
        try:
            self._docker_client.ping()
            return ModuleHealth(
                module_name=self.module_name,
                status=HealthStatus.HEALTHY,
                message="Docker daemon reachable",
            )
        except Exception as exc:
            return ModuleHealth(
                module_name=self.module_name,
                status=HealthStatus.UNHEALTHY,
                message=f"Docker ping failed: {exc}",
            )

    async def execute(
        self,
        code: str,
        language: str = "python",
        user_id: str = "default_user",
        timeout: int | None = None,
    ) -> SandboxResult:
        """
        TODO: Phase 1b - execute code in isolated Docker container.
        """
        # TODO: Phase 1b - implement Docker execution
        return SandboxResult(
            exit_code=1,
            stdout="",
            stderr="DockerSandbox not implemented (Phase 1b)",
        )


__all__ = ["DockerSandbox", "SandboxResult", "DockerSandboxConfig"]

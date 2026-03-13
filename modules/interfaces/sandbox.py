"""
modules/interfaces/sandbox.py - Code execution sandbox interface.

Built-in drivers:
  noop   → modules.sandbox.noop.NoopSandbox    (Phase 1, no Docker)
  docker → modules.sandbox.docker.DockerSandbox (Phase 1b, default)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SandboxResult:
    """Structured result from a sandbox execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    error: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.error


class SandboxInterface(ABC):
    """
    Contract for isolated code execution environments.

    Implementations must enforce resource limits (CPU, memory, time)
    and must not allow filesystem or network access beyond what is
    explicitly permitted.
    """

    @abstractmethod
    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """
        Execute code in an isolated environment.

        Args:
            code:     Source code to execute.
            language: Runtime — "python", "javascript", "bash".
            timeout:  Max execution time in seconds.
            env:      Optional environment variables (safe subset only).

        Returns:
            SandboxResult with stdout, stderr, exit_code, timed_out, error.
        """
        ...

    @abstractmethod
    async def run_bash(
        self,
        command: str,
        timeout: int = 30,
    ) -> SandboxResult:
        """
        Execute a shell command.  Implementations must whitelist commands
        or use Docker isolation to prevent privilege escalation.

        Args:
            command: Shell command string.
            timeout: Max execution time in seconds.

        Returns:
            SandboxResult.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any container / subprocess resources."""
        ...


__all__ = ["SandboxInterface", "SandboxResult"]

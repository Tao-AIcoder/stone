"""
modules/sandbox/noop.py - No-op sandbox for Phase 1 (no Docker required).

WARNING: This sandbox does NOT provide real isolation.
It executes code directly in the host process via subprocess.
Use only in trusted local environments. Switch to DockerSandbox for
production (Phase 1b+).
"""

from __future__ import annotations

import asyncio
import subprocess

from modules.interfaces.sandbox import SandboxInterface, SandboxResult


class NoopSandbox(SandboxInterface):
    """
    Minimal sandbox that runs commands via subprocess without isolation.

    Suitable for Phase 1 local development only.
    """

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        interpreter_map = {
            "python": "python3",
            "javascript": "node",
            "bash": "bash",
        }
        interpreter = interpreter_map.get(language, "python3")

        try:
            proc = await asyncio.create_subprocess_exec(
                interpreter, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return SandboxResult(timed_out=True, error="Execution timed out")

            return SandboxResult(
                stdout=stdout_b.decode(errors="replace"),
                stderr=stderr_b.decode(errors="replace"),
                exit_code=proc.returncode or 0,
            )
        except Exception as exc:
            return SandboxResult(error=str(exc), exit_code=-1)

    async def run_bash(
        self,
        command: str,
        timeout: int = 30,
    ) -> SandboxResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return SandboxResult(timed_out=True, error="Command timed out")

            return SandboxResult(
                stdout=stdout_b.decode(errors="replace"),
                stderr=stderr_b.decode(errors="replace"),
                exit_code=proc.returncode or 0,
            )
        except Exception as exc:
            return SandboxResult(error=str(exc), exit_code=-1)

    async def close(self) -> None:
        pass  # nothing to release


__all__ = ["NoopSandbox"]

"""
tools/bash_tool.py - Safe bash execution tool for STONE Phase 1a.

Only commands from the explicit whitelist are allowed. No Docker sandbox in
Phase 1a. Enforces a 30-second execution timeout.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any

from models.errors import ToolError, ToolTimeoutError
from tools.base import ToolInterface, ToolResult

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT = 30.0  # seconds

# Commands that are safe to run without confirmation
SAFE_COMMANDS: frozenset[str] = frozenset({
    "ls", "cat", "pwd", "echo", "grep", "find", "head", "tail",
    "wc", "date", "df", "du", "ps", "env", "which", "whoami",
    "uname", "hostname", "uptime", "free", "id", "groups",
    "sort", "uniq", "cut", "tr", "sed", "awk", "xargs",
    "stat", "file", "basename", "dirname", "realpath",
})

# Absolutely blocked commands (checked by prefix/substring)
BLOCKED_COMMANDS: frozenset[str] = frozenset({
    "rm", "dd", "mkfs", "chmod", "chown", "curl", "wget",
    "sudo", "su", "ssh", "scp", "rsync", "nc", "ncat",
    "netcat", "python", "python3", "pip", "pip3",
    "perl", "ruby", "php", "node", "npm", "npx",
    "bash", "sh", "zsh", "fish", "csh",
    "kill", "killall", "pkill", "reboot", "shutdown",
    "mount", "umount", "fdisk", "parted",
    "iptables", "ufw", "firewall-cmd",
    "useradd", "userdel", "usermod", "passwd",
    "crontab", "at", "systemctl", "service",
    "docker", "podman", "kubectl",
})


def _get_base_command(command: str) -> str:
    """Extract the first token (base command) from a shell command string."""
    try:
        tokens = shlex.split(command)
        if not tokens:
            return ""
        # Handle env VAR=val cmd or full paths like /usr/bin/ls
        import os
        return os.path.basename(tokens[0])
    except ValueError:
        return command.split()[0] if command.split() else ""


def _is_blocked(command: str) -> bool:
    """Return True if the command contains any blocked pattern."""
    lower = command.lower()
    base = _get_base_command(command).lower()
    if base in BLOCKED_COMMANDS:
        return True
    # Check for pipe or chained commands sneaking in blocked commands
    for blocked in BLOCKED_COMMANDS:
        if f" {blocked} " in f" {lower} " or lower.startswith(blocked + " "):
            return True
    # Block subshell invocations
    if "$(" in command or "`" in command:
        return True
    # Block redirection to important system paths
    dangerous_patterns = [">/etc", ">/usr", ">/bin", ">/sbin", ">>/etc"]
    for pat in dangerous_patterns:
        if pat in command:
            return True
    return False


class BashTool(ToolInterface):
    """
    Execute whitelisted shell commands in Phase 1a (no sandbox).

    Commands in SAFE_COMMANDS do not require user confirmation.
    All other non-blocked commands require_confirmation=True.
    """

    name = "bash_tool"
    description = (
        "在服务器上执行安全的系统命令。仅支持白名单命令（ls, cat, grep, find 等）。"
        "不支持写操作、网络命令或危险命令。"
    )
    requires_confirmation = False  # safe commands; set per-call based on analysis

    async def execute(
        self,
        params: dict[str, Any],
        user_id: str = "default_user",
    ) -> ToolResult:
        command: str = params.get("command", "").strip()
        if not command:
            return ToolResult.fail("命令不能为空")

        base_cmd = _get_base_command(command)

        # Hard block
        if _is_blocked(command):
            logger.warning(
                "BashTool: blocked dangerous command [user=%s]: %r",
                user_id,
                command,
            )
            raise ToolError(
                message=f"命令 {base_cmd!r} 被安全策略禁止",
                tool_name=self.name,
            )

        # Soft block: command not in safe list
        if base_cmd not in SAFE_COMMANDS:
            raise ToolError(
                message=(
                    f"命令 {base_cmd!r} 不在白名单中。"
                    "允许的命令：" + ", ".join(sorted(SAFE_COMMANDS))
                ),
                tool_name=self.name,
            )

        logger.info("BashTool: executing [user=%s]: %r", user_id, command)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=COMMAND_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise ToolTimeoutError(
                    tool_name=self.name,
                    timeout_seconds=COMMAND_TIMEOUT,
                )
        except ToolTimeoutError:
            raise
        except Exception as exc:
            raise ToolError(
                message=f"命令执行失败：{exc}",
                tool_name=self.name,
            ) from exc

        stdout_str = stdout.decode(errors="replace").strip()
        stderr_str = stderr.decode(errors="replace").strip()

        if proc.returncode != 0:
            error_output = stderr_str or f"退出码 {proc.returncode}"
            logger.warning(
                "BashTool: command failed [user=%s] rc=%d: %s",
                user_id,
                proc.returncode,
                error_output[:200],
            )
            return ToolResult.fail(
                error=error_output,
                metadata={"exit_code": proc.returncode, "command": command},
            )

        output = stdout_str
        if stderr_str:
            output += f"\n[stderr]\n{stderr_str}"

        return ToolResult.ok(
            output=output or "(无输出)",
            metadata={"exit_code": 0, "command": command},
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "要执行的 shell 命令。仅支持白名单命令："
                            + ", ".join(sorted(SAFE_COMMANDS))
                        ),
                    }
                },
                "required": ["command"],
            },
        }


__all__ = ["BashTool", "SAFE_COMMANDS", "BLOCKED_COMMANDS"]

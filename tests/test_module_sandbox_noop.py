"""
tests/test_module_sandbox_noop.py - Unit tests for NoopSandbox.

Tests:
- execute() Python code
- run_bash() shell command
- timeout handling
- SandboxInterface compliance
"""

from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.sandbox.noop import NoopSandbox
from modules.interfaces.sandbox import SandboxInterface, SandboxResult


# ── Interface compliance ───────────────────────────────────────────────────────

class TestInterface:
    def test_inherits_sandbox_interface(self) -> None:
        assert issubclass(NoopSandbox, SandboxInterface)

    def test_sandbox_result_success_property(self) -> None:
        r = SandboxResult(stdout="hi", exit_code=0)
        assert r.success is True

    def test_sandbox_result_failure_on_nonzero_exit(self) -> None:
        r = SandboxResult(exit_code=1)
        assert r.success is False

    def test_sandbox_result_failure_on_timeout(self) -> None:
        r = SandboxResult(timed_out=True)
        assert r.success is False

    def test_sandbox_result_failure_on_error(self) -> None:
        r = SandboxResult(error="oops")
        assert r.success is False


# ── execute() ─────────────────────────────────────────────────────────────────

class TestExecute:
    @pytest.fixture
    def sandbox(self) -> NoopSandbox:
        return NoopSandbox()

    @pytest.mark.asyncio
    async def test_simple_print(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.execute("print('hello')", language="python")
        assert result.success
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_exit_code_zero_on_success(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.execute("x = 1 + 1", language="python")
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_nonzero_exit_on_syntax_error(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.execute("def broken(:", language="python")
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_stderr_captured(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.execute(
            "import sys; sys.stderr.write('err\\n')", language="python"
        )
        assert "err" in result.stderr

    @pytest.mark.asyncio
    async def test_timeout_returns_timed_out(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.execute(
            "import time; time.sleep(60)", language="python", timeout=1
        )
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_result_has_all_fields(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.execute("print(42)")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "exit_code")
        assert hasattr(result, "timed_out")
        assert hasattr(result, "error")


# ── run_bash() ────────────────────────────────────────────────────────────────

class TestRunBash:
    @pytest.fixture
    def sandbox(self) -> NoopSandbox:
        return NoopSandbox()

    @pytest.mark.asyncio
    async def test_echo_command(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.run_bash("echo hello")
        assert result.success
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_exit_code_on_failure(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.run_bash("exit 1")
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_timeout_bash(self, sandbox: NoopSandbox) -> None:
        result = await sandbox.run_bash("sleep 60", timeout=1)
        assert result.timed_out is True


# ── close() ───────────────────────────────────────────────────────────────────

class TestClose:
    @pytest.mark.asyncio
    async def test_close_is_noop_and_does_not_raise(self) -> None:
        sandbox = NoopSandbox()
        await sandbox.close()  # must not raise

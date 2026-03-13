"""
tests/test_module_registry.py - Unit tests for modules/registry.py

Verifies:
- DRIVERS dict completeness
- load_driver() returns correct class for every registered driver
- load_driver() raises ConfigError for unknown component/driver
- list_drivers() returns expected structure
"""

from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.errors import ModuleError as ConfigError
from modules.registry import DRIVERS, load_driver, list_drivers
from modules.interfaces import (
    GatewayInterface,
    ShortTermMemoryInterface,
    LongTermMemoryInterface,
    ModelRouterInterface,
    AuthInterface,
    AuditInterface,
    SandboxInterface,
    PromptGuardInterface,
)


# ── DRIVERS structure ─────────────────────────────────────────────────────────

class TestDriversDict:
    EXPECTED_COMPONENTS = {
        "gateway",
        "short_term_memory",
        "long_term_memory",
        "model_router",
        "auth",
        "audit",
        "sandbox",
        "prompt_guard",
        "scheduler",
    }

    def test_all_components_present(self) -> None:
        assert self.EXPECTED_COMPONENTS.issubset(set(DRIVERS.keys()))

    def test_gateway_has_feishu(self) -> None:
        assert "feishu" in DRIVERS["gateway"]

    def test_short_term_memory_has_inmemory(self) -> None:
        assert "inmemory" in DRIVERS["short_term_memory"]

    def test_long_term_memory_has_sqlite(self) -> None:
        assert "sqlite" in DRIVERS["long_term_memory"]

    def test_model_router_has_direct(self) -> None:
        assert "direct" in DRIVERS["model_router"]

    def test_auth_has_whitelist(self) -> None:
        assert "whitelist" in DRIVERS["auth"]

    def test_audit_has_sqlite(self) -> None:
        assert "sqlite" in DRIVERS["audit"]

    def test_sandbox_has_noop_and_docker(self) -> None:
        assert "noop" in DRIVERS["sandbox"]
        assert "docker" in DRIVERS["sandbox"]

    def test_prompt_guard_has_regex(self) -> None:
        assert "regex" in DRIVERS["prompt_guard"]

    def test_driver_paths_have_colon(self) -> None:
        for comp, drivers in DRIVERS.items():
            for driver_name, path in drivers.items():
                assert ":" in path, (
                    f"DRIVERS[{comp!r}][{driver_name!r}] = {path!r} missing ':'"
                )


# ── load_driver() ─────────────────────────────────────────────────────────────

class TestLoadDriver:
    def test_load_inmemory_store(self) -> None:
        cls = load_driver("short_term_memory", "inmemory")
        from modules.memory.inmemory_store import InMemoryStore
        assert cls is InMemoryStore

    def test_load_sqlite_store(self) -> None:
        cls = load_driver("long_term_memory", "sqlite")
        from modules.memory.sqlite_store import SQLiteStore
        assert cls is SQLiteStore

    def test_load_auth_manager(self) -> None:
        cls = load_driver("auth", "whitelist")
        from security.auth import AuthManager
        assert cls is AuthManager

    def test_load_audit_logger(self) -> None:
        cls = load_driver("audit", "sqlite")
        from security.audit import AuditLogger
        assert cls is AuditLogger

    def test_load_prompt_guard(self) -> None:
        cls = load_driver("prompt_guard", "regex")
        from security.prompt_guard import PromptGuard
        assert cls is PromptGuard

    def test_load_noop_sandbox(self) -> None:
        cls = load_driver("sandbox", "noop")
        from modules.sandbox.noop import NoopSandbox
        assert cls is NoopSandbox

    def test_load_model_router(self) -> None:
        cls = load_driver("model_router", "direct")
        from core.model_router import ModelRouter
        assert cls is ModelRouter

    def test_unknown_component_raises_config_error(self) -> None:
        with pytest.raises(ConfigError, match="Unknown component"):
            load_driver("nonexistent", "driver")

    def test_unknown_driver_raises_config_error(self) -> None:
        with pytest.raises(ConfigError, match="Unknown driver"):
            load_driver("auth", "nonexistent_driver")


# ── Interface compliance ───────────────────────────────────────────────────────

class TestInterfaceCompliance:
    """Loaded classes must be subclasses of their declared interface."""

    def test_inmemory_store_is_short_term(self) -> None:
        cls = load_driver("short_term_memory", "inmemory")
        assert issubclass(cls, ShortTermMemoryInterface)

    def test_sqlite_store_is_long_term(self) -> None:
        cls = load_driver("long_term_memory", "sqlite")
        assert issubclass(cls, LongTermMemoryInterface)

    def test_auth_manager_is_auth_interface(self) -> None:
        cls = load_driver("auth", "whitelist")
        assert issubclass(cls, AuthInterface)

    def test_audit_logger_is_audit_interface(self) -> None:
        cls = load_driver("audit", "sqlite")
        assert issubclass(cls, AuditInterface)

    def test_prompt_guard_is_guard_interface(self) -> None:
        cls = load_driver("prompt_guard", "regex")
        assert issubclass(cls, PromptGuardInterface)

    def test_noop_sandbox_is_sandbox_interface(self) -> None:
        cls = load_driver("sandbox", "noop")
        assert issubclass(cls, SandboxInterface)

    def test_model_router_is_router_interface(self) -> None:
        cls = load_driver("model_router", "direct")
        assert issubclass(cls, ModelRouterInterface)

    def test_feishu_gateway_is_gateway_interface(self) -> None:
        cls = load_driver("gateway", "feishu")
        assert issubclass(cls, GatewayInterface)


# ── list_drivers() ────────────────────────────────────────────────────────────

class TestListDrivers:
    def test_returns_all_components_when_no_arg(self) -> None:
        result = list_drivers()
        assert isinstance(result, dict)
        assert "gateway" in result
        assert "auth" in result

    def test_returns_list_of_driver_names(self) -> None:
        result = list_drivers("auth")
        assert result == {"auth": ["whitelist"]}

    def test_unknown_component_raises(self) -> None:
        with pytest.raises(ConfigError):
            list_drivers("no_such_component")

"""
modules/registry.py - Driver registry for dynamic module loading.

Maps component → driver_name → "module.path:ClassName".
load_driver(component, driver_name) dynamically imports and returns the class.

Usage:
    cls = load_driver("gateway", "feishu")
    gateway = cls(config=..., agent=...)
"""

from __future__ import annotations

import importlib
from typing import Any, Type

from models.errors import ModuleError as ConfigError


# ── Driver Registry ────────────────────────────────────────────────────────────

DRIVERS: dict[str, dict[str, str]] = {
    # ── Gateway (messaging platform) ──────────────────────────────────────────
    "gateway": {
        "feishu":   "modules.gateway.feishu:FeishuGateway",
        "telegram": "modules.gateway.telegram:TelegramGateway",   # Phase 2
        "wechat":   "modules.gateway.wechat:WeChatGateway",       # Phase 2
    },

    # ── Short-term memory (session store) ─────────────────────────────────────
    "short_term_memory": {
        "inmemory": "modules.memory.inmemory_store:InMemoryStore",
        "redis":    "modules.memory.redis_store:RedisStore",       # Phase 2
    },

    # ── Long-term memory (persistent store) ───────────────────────────────────
    "long_term_memory": {
        "sqlite":   "modules.memory.sqlite_store:SQLiteStore",
        "postgres": "modules.memory.postgres_store:PostgresStore", # Future
    },

    # ── Model router ──────────────────────────────────────────────────────────
    "model_router": {
        "direct": "core.model_router:ModelRouter",
    },

    # ── Authentication ────────────────────────────────────────────────────────
    "auth": {
        "whitelist": "security.auth:AuthManager",
    },

    # ── Audit logger ──────────────────────────────────────────────────────────
    "audit": {
        "sqlite": "security.audit:AuditLogger",
    },

    # ── Code execution sandbox ────────────────────────────────────────────────
    "sandbox": {
        "noop":   "modules.sandbox.noop:NoopSandbox",
        "docker": "modules.sandbox.docker:DockerSandbox",
    },

    # ── Prompt injection guard ────────────────────────────────────────────────
    "prompt_guard": {
        "regex": "security.prompt_guard:PromptGuard",
    },

    # ── Scheduler ─────────────────────────────────────────────────────────────
    "scheduler": {
        "apscheduler": "core.scheduler:Scheduler",
    },
}


# ── Loader ────────────────────────────────────────────────────────────────────

def load_driver(component: str, driver_name: str) -> Type[Any]:
    """
    Dynamically import and return the class for the given component driver.

    Args:
        component:   Key in DRIVERS (e.g. "gateway", "auth").
        driver_name: Driver variant (e.g. "feishu", "whitelist").

    Returns:
        The uninstantiated class.

    Raises:
        ConfigError: If component or driver_name is not registered.
        ImportError: If the module cannot be imported.
    """
    if component not in DRIVERS:
        raise ConfigError(
            f"Unknown component '{component}'. "
            f"Available: {sorted(DRIVERS.keys())}"
        )

    comp_drivers = DRIVERS[component]
    if driver_name not in comp_drivers:
        raise ConfigError(
            f"Unknown driver '{driver_name}' for component '{component}'. "
            f"Available: {sorted(comp_drivers.keys())}"
        )

    module_path, class_name = comp_drivers[driver_name].rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls


def list_drivers(component: str | None = None) -> dict[str, list[str]]:
    """
    Return registered drivers.

    Args:
        component: If given, return only drivers for that component.

    Returns:
        dict mapping component → list of driver names.
    """
    if component:
        if component not in DRIVERS:
            raise ConfigError(f"Unknown component '{component}'.")
        return {component: list(DRIVERS[component].keys())}
    return {comp: list(drivers.keys()) for comp, drivers in DRIVERS.items()}


__all__ = ["DRIVERS", "load_driver", "list_drivers"]

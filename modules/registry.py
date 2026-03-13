"""
modules/registry.py - Driver registry for dynamic module loading.

Maps component → driver_name → "module.path:ClassName".
load_driver(component, driver_name) dynamically imports and returns the class.

Usage:
    cls = load_driver("gateway", "feishu")
    gateway = cls(agent=..., auth=..., ...)

Driver status legend:
  ✓  implemented and tested
  ~  stub (planned, not yet implemented — will raise if called)
"""

from __future__ import annotations

import importlib
from typing import Any, Type

from models.errors import ModuleError as ConfigError


# ── Driver Registry ────────────────────────────────────────────────────────────

DRIVERS: dict[str, dict[str, str]] = {
    # ── Gateway (messaging platform) ──────────────────────────────────────────
    # Third-party alternatives: Telegram Bot API, WeChat Official Account,
    # Slack Bolt, Discord.py, WeCom (企业微信)
    "gateway": {
        "feishu":   "modules.gateway.feishu:FeishuGateway",       # ✓ Phase 1
        "telegram": "modules.gateway.telegram:TelegramGateway",   # ~ Phase 2
        "wechat":   "modules.gateway.wechat:WeChatGateway",       # ~ Phase 2
    },

    # ── Short-term memory (session store) ─────────────────────────────────────
    # Third-party alternatives: Redis, Memcached, DragonflyDB
    "short_term_memory": {
        "inmemory": "modules.memory.inmemory_store:InMemoryStore",  # ✓ Phase 1
        "redis":    "modules.memory.redis_store:RedisStore",        # ~ Phase 2
    },

    # ── Long-term memory (persistent store) ───────────────────────────────────
    # Third-party alternatives: PostgreSQL, MySQL, TiDB
    "long_term_memory": {
        "sqlite":   "modules.memory.sqlite_store:SQLiteStore",       # ✓ Phase 1
        "postgres": "modules.memory.postgres_store:PostgresStore",   # ~ future
    },

    # ── Model router ──────────────────────────────────────────────────────────
    # Third-party alternatives: LiteLLM, OpenRouter, aisuite
    "model_router": {
        "direct": "core.model_router:ModelRouter",  # ✓ Phase 1
    },

    # ── Authentication ────────────────────────────────────────────────────────
    # Third-party alternatives: OAuth2/OIDC, LDAP, Keycloak, JWT
    "auth": {
        "whitelist": "security.auth:AuthManager",  # ✓ Phase 1
    },

    # ── Audit logger ──────────────────────────────────────────────────────────
    # Third-party alternatives: ELK Stack, Loki+Grafana, CloudWatch, Datadog
    "audit": {
        "sqlite": "security.audit:AuditLogger",  # ✓ Phase 1
    },

    # ── Code execution sandbox ────────────────────────────────────────────────
    # Third-party alternatives: Docker, Firecracker, E2B, Daytona, Seatbelt (macOS)
    "sandbox": {
        "noop":   "modules.sandbox.noop:NoopSandbox",      # ✓ Phase 1 (no isolation)
        "docker": "modules.sandbox.docker:DockerSandbox",  # ~ Phase 1b
    },

    # ── Prompt injection guard ────────────────────────────────────────────────
    # Third-party alternatives: Llama Guard, OpenAI Moderation API,
    # Lakera Guard, Rebuff
    "prompt_guard": {
        "regex": "security.prompt_guard:PromptGuard",  # ✓ Phase 1
    },

    # ── Task scheduler ────────────────────────────────────────────────────────
    # Third-party alternatives: Celery+Redis, RQ, Dramatiq, Huey
    "scheduler": {
        "apscheduler": "core.scheduler:Scheduler",  # ✓ Phase 1
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
        ImportError: If the target module cannot be imported.
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
    return getattr(module, class_name)


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

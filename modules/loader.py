"""
modules/loader.py - Module loader with ordered startup for STONE (默行者)

All replaceable modules are loaded via modules/registry.py based on the
"driver" fields in stone.config.json.  To swap any module:
  1. Set the "driver" field in stone.config.json.
  2. Ensure the target class is registered in modules/registry.py.
  No code changes required.

Startup order (14 steps):
  1.  config.py / env
  2.  stone.config.json parse + validate
  3.  auth            [critical — driver: modules.auth.driver]
  4.  audit           [critical — driver: modules.audit.driver]
  5.  long-term store [driver: modules.memory.long_term.driver]
  6.  short-term store [driver: modules.memory.short_term.driver]
  7.  sandbox         [non-fatal — driver: modules.sandbox.driver]
  8.  prompt_guard    [driver: modules.prompt_guard.driver]
  9.  model_router    [driver: modules.model_router.driver]
  10. skill registry
  11. scheduler       [driver: modules.scheduler.driver]
  12. (state machine instantiated inside Agent)
  13. agent
  14. gateway         [last — driver: modules.gateway.driver]
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from config import get_settings
from models.errors import ModuleError
from modules.registry import load_driver

logger = logging.getLogger(__name__)


class ModuleLoader:
    """
    Orchestrates module initialization in the correct dependency order.

    Every replaceable module is resolved via load_driver() which reads
    the DRIVERS registry and dynamically imports the configured class.
    The "driver" value is pulled from stone.config.json at runtime.
    """

    def __init__(self) -> None:
        # References to initialized components (populated during startup)
        self.sqlite_store: Any = None      # long-term store instance
        self.inmemory_store: Any = None    # short-term store instance
        self.auth: Any = None
        self.audit: Any = None
        self.sandbox: Any = None
        self.prompt_guard: Any = None
        self.model_router: Any = None
        self.skill_registry: Any = None
        self.scheduler: Any = None
        self.context_manager: Any = None
        self.dry_run_manager: Any = None
        self.agent: Any = None
        self.gateway: Any = None

        self._started = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _driver(cfg: dict[str, Any], *path: str) -> str:
        """
        Navigate nested stone.config.json dict and return the driver string.

        Example: _driver(cfg, "modules", "gateway", "driver") → "feishu"
        Raises ConfigError (via load_driver) if the path or key is missing.
        """
        node: Any = cfg
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return ""  # caller handles missing with a default
            node = node[key]
        return str(node) if node else ""

    # ── Startup ───────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Run all 14 initialization steps."""
        logger.info("=" * 60)
        logger.info("STONE (默行者) startup sequence beginning")
        logger.info("=" * 60)

        # Step 1: .env / pydantic settings
        logger.info("[1/14] Loading configuration...")
        cfg = get_settings()
        sc = cfg.stone_config          # shorthand for stone.config.json dict
        logger.info("Configuration loaded: log_level=%s", cfg.log_level)

        # Step 2: stone.config.json structural check
        logger.info("[2/14] Parsing stone.config.json...")
        _validate_stone_config(sc)
        logger.info("stone.config.json validated")

        # Step 3: Auth [critical]
        logger.info("[3/14] Initializing auth module...")
        auth_driver = self._driver(sc, "modules", "auth", "driver") or "whitelist"
        try:
            AuthClass = load_driver("auth", auth_driver)
            self.auth = AuthClass()
            logger.info(
                "Auth ready (driver=%s, whitelist=%d users)",
                auth_driver,
                len(cfg.admin_whitelist),
            )
        except Exception as exc:
            raise ModuleError(
                message=f"auth 模块初始化失败（致命）: {exc}",
                module_name="auth",
            ) from exc

        # Step 4: Long-term store + Audit [critical]
        logger.info("[4/14] Initializing long-term store + audit module...")
        lt_driver = self._driver(sc, "modules", "memory", "long_term", "driver") or "sqlite"
        audit_driver = self._driver(sc, "modules", "audit", "driver") or "sqlite"
        try:
            LTClass = load_driver("long_term_memory", lt_driver)
            self.sqlite_store = LTClass()
            await self.sqlite_store.initialize()

            AuditClass = load_driver("audit", audit_driver)
            self.audit = AuditClass(sqlite_store=self.sqlite_store)
            logger.info(
                "Long-term store ready (driver=%s), audit ready (driver=%s)",
                lt_driver,
                audit_driver,
            )
        except Exception as exc:
            raise ModuleError(
                message=f"audit/long-term 模块初始化失败（致命）: {exc}",
                module_name="audit",
            ) from exc

        # Step 5: (long-term store already initialized in step 4)
        logger.info("[5/14] Long-term store already initialized (shared from step 4)")

        # Step 6: Short-term store
        logger.info("[6/14] Initializing short-term store...")
        st_driver = (
            self._driver(sc, "modules", "memory", "short_term", "driver") or "inmemory"
        )
        STClass = load_driver("short_term_memory", st_driver)
        self.inmemory_store = STClass()
        logger.info("Short-term store ready (driver=%s)", st_driver)

        # Step 7: Sandbox [non-fatal]
        logger.info("[7/14] Initializing sandbox...")
        sb_driver = self._driver(sc, "modules", "sandbox", "driver") or "noop"
        try:
            SBClass = load_driver("sandbox", sb_driver)
            self.sandbox = SBClass()
            if hasattr(self.sandbox, "initialize"):
                await self.sandbox.initialize()
            logger.info("Sandbox ready (driver=%s)", sb_driver)
        except Exception as exc:
            logger.warning(
                "Sandbox init failed (non-fatal, driver=%s): %s", sb_driver, exc
            )
            # Fall back to noop
            from modules.sandbox.noop import NoopSandbox
            self.sandbox = NoopSandbox()
            logger.info("Sandbox fallback: NoopSandbox")

        # Step 8: Prompt guard
        logger.info("[8/14] Initializing prompt guard...")
        pg_driver = self._driver(sc, "modules", "prompt_guard", "driver") or "regex"
        PGClass = load_driver("prompt_guard", pg_driver)
        self.prompt_guard = PGClass()
        logger.info("Prompt guard ready (driver=%s)", pg_driver)

        # Step 9: Model router
        logger.info("[9/14] Initializing model router...")
        mr_driver = self._driver(sc, "modules", "model_router", "driver") or "direct"
        MRClass = load_driver("model_router", mr_driver)
        self.model_router = MRClass()
        logger.info(
            "Model router ready (driver=%s, default_model=%s)",
            mr_driver,
            cfg.default_model,
        )

        # Step 10: Skill registry
        logger.info("[10/14] Initializing skill registry...")
        from registry.skill_registry import SkillRegistry
        self.skill_registry = SkillRegistry()
        self.skill_registry.register_phase1a_tools()
        logger.info(
            "Skill registry ready (%d tools)", len(self.skill_registry.list_tools())
        )

        # Step 11: Scheduler
        logger.info("[11/14] Initializing scheduler...")
        sched_driver = (
            self._driver(sc, "modules", "scheduler", "driver") or "apscheduler"
        )
        SchedClass = load_driver("scheduler", sched_driver)
        self.scheduler = SchedClass(sqlite_store=self.sqlite_store)
        logger.info("Scheduler instantiated (driver=%s)", sched_driver)

        # Step 12: State machine (instantiated inside Agent)
        logger.info("[12/14] State machine will be initialized with agent")

        # Step 13: Agent
        logger.info("[13/14] Initializing agent...")
        from core.context_manager import ContextManager
        from core.dry_run import DryRunManager
        from core.agent import Agent

        self.context_manager = ContextManager(
            short_term=self.inmemory_store,
            long_term=self.sqlite_store,
            model_router=self.model_router,
        )
        self.dry_run_manager = DryRunManager(audit_logger=self.audit)
        self.agent = Agent(
            model_router=self.model_router,
            skill_registry=self.skill_registry,
            context_manager=self.context_manager,
            dry_run_manager=self.dry_run_manager,
            audit_logger=self.audit,
        )
        # Wire agent into scheduler and start
        self.scheduler.agent = self.agent
        await self.scheduler.start()
        logger.info("Agent ready, scheduler started")

        # Step 14: Gateway [last]
        logger.info("[14/14] Initializing gateway...")
        gw_driver = self._driver(sc, "modules", "gateway", "driver") or "feishu"
        if cfg.feishu_app_id and cfg.feishu_app_secret:
            try:
                GWClass = load_driver("gateway", gw_driver)
                self.gateway = GWClass(
                    agent=self.agent,
                    auth=self.auth,
                    prompt_guard=self.prompt_guard,
                    audit=self.audit,
                )
                asyncio.ensure_future(self.gateway.start())
                logger.info("Gateway started in background (driver=%s)", gw_driver)
            except Exception as exc:
                logger.warning("Gateway init failed (non-fatal): %s", exc)
        else:
            logger.warning("Gateway credentials not configured — gateway not started")

        self._started = True
        logger.info("=" * 60)
        logger.info("STONE (默行者) startup complete")
        logger.info("=" * 60)

        await self.audit.log(
            level="INFO",
            action="system_startup",
            user_id="system",
            detail={
                "version": sc.get("stone", {}).get("version", "unknown"),
                "drivers": {
                    "auth": auth_driver,
                    "long_term_memory": lt_driver,
                    "short_term_memory": st_driver,
                    "sandbox": sb_driver,
                    "prompt_guard": pg_driver,
                    "model_router": mr_driver,
                    "scheduler": sched_driver,
                    "gateway": gw_driver,
                },
            },
            result="success",
        )

    # ── Shutdown ──────────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Graceful shutdown in reverse order."""
        logger.info("STONE (默行者) shutting down...")

        if self.gateway:
            try:
                await self.gateway.stop()
            except Exception as exc:
                logger.warning("Gateway shutdown error: %s", exc)

        if self.scheduler:
            try:
                await self.scheduler.stop()
            except Exception as exc:
                logger.warning("Scheduler shutdown error: %s", exc)

        if self.model_router:
            try:
                await self.model_router.close()
            except Exception as exc:
                logger.warning("ModelRouter shutdown error: %s", exc)

        if self.sandbox:
            try:
                await self.sandbox.close()
            except Exception as exc:
                logger.warning("Sandbox shutdown error: %s", exc)

        if self.sqlite_store:
            try:
                await self.sqlite_store.close()
            except Exception as exc:
                logger.warning("SQLiteStore shutdown error: %s", exc)

        logger.info("STONE (默行者) shutdown complete")


def _validate_stone_config(config: dict) -> None:
    """Basic structural validation of stone.config.json."""
    for key in ("stone", "agent", "modules"):
        if key not in config:
            raise ModuleError(
                message=f"stone.config.json 缺少必要字段: {key!r}",
                module_name="config",
            )


__all__ = ["ModuleLoader"]

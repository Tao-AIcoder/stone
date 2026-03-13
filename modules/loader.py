"""
modules/loader.py - Module loader with ordered startup for STONE (默行者)

Follows the exact 14-step initialization sequence from the PRD.
Critical steps (auth, audit) will abort startup if they fail.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config import get_settings, settings
from models.errors import ModuleError

logger = logging.getLogger(__name__)

_CONFIG_FILE = Path(__file__).parent.parent / "stone.config.json"


class ModuleLoader:
    """
    Orchestrates module initialization in the correct dependency order.

    Startup order:
    1.  config.py
    2.  stone.config.json parse + validate
    3.  security/auth           [critical]
    4.  security/audit          [critical]
    5.  memory/sqlite
    6.  memory/inmemory
    7.  security/sandbox        (Docker check)
    8.  security/prompt_guard
    9.  model_router
    10. registry/skills
    11. core/scheduler
    12. core/state_machine
    13. core/agent
    14. gateway/feishu          [last]
    """

    def __init__(self) -> None:
        # References to initialized components (populated during startup)
        self.sqlite_store: Any = None
        self.inmemory_store: Any = None
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

    async def startup(self) -> None:
        """Run all 14 initialization steps."""
        logger.info("=" * 60)
        logger.info("STONE (默行者) startup sequence beginning")
        logger.info("=" * 60)

        # Step 1: Config
        logger.info("[1/14] Loading configuration...")
        cfg = get_settings()
        logger.info("Configuration loaded: log_level=%s", cfg.log_level)

        # Step 2: stone.config.json
        logger.info("[2/14] Parsing stone.config.json...")
        _validate_stone_config(cfg.stone_config)
        logger.info("stone.config.json validated")

        # Step 3: Auth [critical]
        logger.info("[3/14] Initializing security/auth...")
        try:
            from security.auth import AuthManager
            self.auth = AuthManager()
            logger.info("Auth module ready (whitelist: %d users)", len(cfg.admin_whitelist))
        except Exception as exc:
            raise ModuleError(
                message=f"auth 模块初始化失败（致命）: {exc}",
                module_name="security/auth",
            ) from exc

        # Step 4: Audit [critical]
        logger.info("[4/14] Initializing security/audit...")
        try:
            from modules.memory.sqlite_store import SQLiteStore
            # Temporarily create SQLite store for audit (will be shared below)
            self.sqlite_store = SQLiteStore()
            await self.sqlite_store.initialize()

            from security.audit import AuditLogger
            self.audit = AuditLogger(sqlite_store=self.sqlite_store)
            logger.info("Audit module ready")
        except Exception as exc:
            raise ModuleError(
                message=f"audit 模块初始化失败（致命）: {exc}",
                module_name="security/audit",
            ) from exc

        # Step 5: memory/sqlite (already initialized in step 4, share instance)
        logger.info("[5/14] SQLite store already initialized (shared from step 4)")

        # Step 6: memory/inmemory
        logger.info("[6/14] Initializing memory/inmemory...")
        from modules.memory.inmemory_store import InMemoryStore
        self.inmemory_store = InMemoryStore()
        logger.info("In-memory store ready")

        # Step 7: security/sandbox (Docker check - non-fatal)
        logger.info("[7/14] Checking Docker sandbox...")
        from modules.sandbox.docker import DockerSandbox
        self.sandbox = DockerSandbox()
        try:
            await self.sandbox.initialize()
        except Exception as exc:
            logger.warning("Docker sandbox check failed (non-fatal): %s", exc)

        # Step 8: security/prompt_guard
        logger.info("[8/14] Initializing prompt guard...")
        from security.prompt_guard import PromptGuard
        self.prompt_guard = PromptGuard()
        logger.info("Prompt guard ready")

        # Step 9: model_router
        logger.info("[9/14] Initializing model router...")
        from core.model_router import ModelRouter
        self.model_router = ModelRouter()
        logger.info("Model router ready (default: %s)", cfg.default_model)

        # Step 10: registry/skills
        logger.info("[10/14] Initializing skill registry...")
        from registry.skill_registry import SkillRegistry
        self.skill_registry = SkillRegistry()
        self.skill_registry.register_phase1a_tools()
        logger.info(
            "Skill registry ready (%d tools registered)",
            len(self.skill_registry.list_tools()),
        )

        # Step 11: core/scheduler
        logger.info("[11/14] Initializing scheduler...")
        from core.scheduler import Scheduler
        self.scheduler = Scheduler(sqlite_store=self.sqlite_store)

        # Step 12: core/state_machine (instantiated inside Agent)
        logger.info("[12/14] State machine will be initialized with agent")

        # Step 13: core/agent
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
        logger.info("Agent ready")

        # Wire agent into scheduler now that it's available
        self.scheduler.agent = self.agent
        await self.scheduler.start()
        logger.info("Scheduler started")

        # Step 14: gateway/feishu [last]
        logger.info("[14/14] Initializing Feishu gateway...")
        if cfg.feishu_app_id and cfg.feishu_app_secret:
            from modules.gateway.feishu import FeishuGateway
            self.gateway = FeishuGateway(
                agent=self.agent,
                auth=self.auth,
                prompt_guard=self.prompt_guard,
                audit=self.audit,
            )
            # Start in background - don't await (it blocks)
            import asyncio
            asyncio.ensure_future(self.gateway.start())
            logger.info("Feishu gateway started in background")
        else:
            logger.warning(
                "Feishu credentials not configured - gateway not started"
            )

        self._started = True
        logger.info("=" * 60)
        logger.info("STONE (默行者) startup complete")
        logger.info("=" * 60)

        await self.audit.log(
            level="INFO",
            action="system_startup",
            user_id="system",
            detail={"version": cfg.stone_config.get("stone", {}).get("version", "unknown")},
            result="success",
        )

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

        if self.sqlite_store:
            try:
                await self.sqlite_store.close()
            except Exception as exc:
                logger.warning("SQLiteStore shutdown error: %s", exc)

        logger.info("STONE (默行者) shutdown complete")


def _validate_stone_config(config: dict[str, Any]) -> None:
    """Basic structural validation of stone.config.json."""
    required_keys = ["stone", "agent", "modules"]
    for key in required_keys:
        if key not in config:
            raise ModuleError(
                message=f"stone.config.json 缺少必要字段: {key!r}",
                module_name="config",
            )


__all__ = ["ModuleLoader"]

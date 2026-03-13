"""
tests/conftest.py - Shared fixtures for STONE test suite.

Provides a mock ModuleLoader and a FastAPI TestClient that does NOT
require a running Feishu connection, SQLite, or any external services.
"""

from __future__ import annotations

import sys
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Mock Loader Factory ────────────────────────────────────────────────────────

def make_mock_loader(whitelist: list[str] | None = None) -> MagicMock:
    """
    Build a fully mocked ModuleLoader that satisfies all API handler
    attribute accesses without touching real infrastructure.
    """
    loader = MagicMock()

    # Auth
    auth = MagicMock()
    auth.verify_user = MagicMock(
        side_effect=lambda oid: oid in (whitelist or ["open_id_admin"])
    )
    auth.verify_pin = AsyncMock(return_value=True)
    auth.check_rate_limit = MagicMock(return_value=True)
    loader.auth = auth

    # Audit
    loader.audit = MagicMock()
    loader.audit.log = AsyncMock()

    # SQLite store
    sqlite = MagicMock()
    sqlite.db = MagicMock()
    sqlite.db.execute = AsyncMock()
    sqlite.get_conversation_messages = AsyncMock(return_value=[])
    sqlite.get_conversation = AsyncMock(return_value=None)
    sqlite.get_long_term_memories = AsyncMock(return_value=[])
    sqlite.get_audit_logs = AsyncMock(return_value=[])
    sqlite.get_memories = AsyncMock(return_value=[])
    loader.sqlite_store = sqlite

    # InMemory store
    loader.inmemory_store = MagicMock()

    # Model router
    loader.model_router = MagicMock()

    # Prompt guard
    guard = MagicMock()
    guard.scan = MagicMock(return_value=True)
    loader.prompt_guard = guard

    # Dry-run manager
    dry_run = MagicMock()
    dry_run.has_pending = MagicMock(return_value=False)
    dry_run.confirm = AsyncMock()
    dry_run.cancel = AsyncMock()
    loader.dry_run_manager = dry_run

    # Agent
    from models.message import BotResponse
    import uuid
    from datetime import datetime

    default_response = BotResponse(
        response_id=str(uuid.uuid4()),
        conv_id=str(uuid.uuid4()),
        content="好的，我明白了。",
        requires_confirmation=False,
        confirmation_token="",
        tools_used=[],
        is_error=False,
        timestamp=datetime.utcnow(),
    )
    loader.agent = MagicMock()
    loader.agent.process = AsyncMock(return_value=default_response)

    # Gateway
    loader.gateway = MagicMock()
    loader.gateway._running = True

    # Scheduler
    mock_task = MagicMock()
    mock_task.task_id = "task-001"
    mock_task.name = "daily_news"
    mock_task.cron_expr = "0 8 * * *"
    mock_task.action = "总结新闻"
    mock_task.enabled = True
    mock_task.last_run = None
    from datetime import datetime
    mock_task.created_at = datetime.utcnow()

    loader.scheduler = MagicMock()
    loader.scheduler._tasks = {}
    loader.scheduler.list_tasks = MagicMock(return_value=[])
    loader.scheduler.get_tasks = AsyncMock(return_value=[])
    loader.scheduler.add_task = AsyncMock(return_value=mock_task)
    loader.scheduler.pause_task = AsyncMock()
    loader.scheduler.resume_task = AsyncMock()
    loader.scheduler.delete_task = AsyncMock()

    # Skill registry
    from models.skill import Skill, SkillCategory
    mock_skill = Skill(
        name="file_tool",
        display_name="File Tool",
        description="Read and write files",
        category=SkillCategory.FILE,
    )
    loader.skill_registry = MagicMock()
    loader.skill_registry.list_skills = MagicMock(return_value=[mock_skill])
    loader.skill_registry.list_tools = MagicMock(return_value=[mock_skill])

    return loader


def make_test_app(loader: Any | None = None) -> Any:
    """Create a FastAPI app with a pre-injected mock loader (bypasses lifespan)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from api.health import router as health_router
    from api.chat import router as chat_router
    from api.admin import router as admin_router
    from models.errors import AuthError, PermissionError, PromptInjectionError, StoneError
    from fastapi import Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="STONE Test App")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(admin_router)

    # Inject mock loader directly into app state
    app.state.loader = loader or make_mock_loader()

    @app.exception_handler(PromptInjectionError)
    async def handle_prompt_injection(request: Request, exc: PromptInjectionError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "PROMPT_INJECTION", "message": exc.message})

    @app.exception_handler(AuthError)
    async def handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(PermissionError)
    async def handle_permission_error(request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(StoneError)
    async def handle_stone_error(request: Request, exc: StoneError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": exc.code, "message": exc.message})

    return app


# ── Shared Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_loader() -> MagicMock:
    return make_mock_loader()


@pytest.fixture
def client(mock_loader: MagicMock) -> TestClient:
    app = make_test_app(loader=mock_loader)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Headers that pass admin auth checks."""
    return {
        "X-Open-Id": "open_id_admin",
        "X-Admin-Pin": "1234",
    }

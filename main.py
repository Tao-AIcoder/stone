"""
main.py - FastAPI application entry point for STONE (默行者)

Starts all modules via ModuleLoader in a lifespan context manager.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from models.errors import (
    AuthError,
    PermissionError,
    PromptInjectionError,
    StoneError,
)

logger = logging.getLogger(__name__)

# ── Module Loader singleton ───────────────────────────────────────────────────

_loader: Any = None


def get_loader() -> Any:
    return _loader


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    global _loader

    from modules.loader import ModuleLoader

    _loader = ModuleLoader()
    app.state.loader = _loader

    try:
        await _loader.startup()
        logger.info("STONE application ready")
        yield
    finally:
        logger.info("STONE application shutting down...")
        if _loader is not None:
            await _loader.shutdown()
        logger.info("STONE application stopped")


# ── App Factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="STONE (默行者)",
        description="Personal AI assistant system - self-hosted, privacy-first",
        version=settings.stone_config.get("stone", {}).get("version", "1.0.0"),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    from api.health import router as health_router
    from api.chat import router as chat_router
    from api.admin import router as admin_router

    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(admin_router)

    # ── Exception Handlers ────────────────────────────────────────────────────

    @app.exception_handler(PromptInjectionError)
    async def handle_prompt_injection(
        request: Request, exc: PromptInjectionError
    ) -> JSONResponse:
        logger.warning("PromptInjection blocked: %s", exc.message)
        return JSONResponse(
            status_code=400,
            content={
                "error": "PROMPT_INJECTION",
                "message": "请求被安全策略拦截",
            },
        )

    @app.exception_handler(AuthError)
    async def handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"error": exc.code, "message": exc.message},
        )

    @app.exception_handler(PermissionError)
    async def handle_permission_error(
        request: Request, exc: PermissionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"error": exc.code, "message": exc.message},
        )

    @app.exception_handler(StoneError)
    async def handle_stone_error(request: Request, exc: StoneError) -> JSONResponse:
        logger.warning("StoneError: %s", exc.message)
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def handle_generic_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": "服务器内部错误"},
        )

    return app


app = create_app()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level.lower(),
        reload=False,
    )

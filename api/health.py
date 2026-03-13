"""
api/health.py - Health check endpoint for STONE (默行者)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["health"])

_START_TIME = datetime.utcnow()


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """
    Returns system health status.

    Response format:
    {
        "status": "healthy" | "degraded" | "unhealthy",
        "version": "1.0.0",
        "uptime_seconds": 123,
        "timestamp": "2024-01-01T00:00:00",
        "modules": {
            "model_router": "healthy",
            "sqlite": "healthy",
            "feishu_gateway": "healthy" | "disconnected",
            ...
        }
    }
    """
    from config import settings

    uptime = (datetime.utcnow() - _START_TIME).total_seconds()

    # Gather module health from app state (set during startup)
    from main import get_loader
    loader = get_loader()

    modules: dict[str, str] = {}

    if loader is not None:
        # SQLite
        if loader.sqlite_store is not None:
            try:
                await loader.sqlite_store.db.execute("SELECT 1")
                modules["sqlite"] = "healthy"
            except Exception:
                modules["sqlite"] = "unhealthy"
        else:
            modules["sqlite"] = "not_initialized"

        # Model router (check Ollama ping)
        if loader.model_router is not None:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(
                        f"{settings.ollama_base_url}/api/tags"
                    )
                    modules["ollama"] = "healthy" if resp.status_code == 200 else "degraded"
            except Exception:
                modules["ollama"] = "unreachable"
        else:
            modules["ollama"] = "not_initialized"

        # Feishu gateway
        if loader.gateway is not None:
            modules["feishu_gateway"] = (
                "healthy" if loader.gateway._running else "stopped"
            )
        else:
            modules["feishu_gateway"] = "not_configured"

        # Scheduler
        if loader.scheduler is not None:
            task_count = sum(1 for _ in loader.scheduler._tasks)
            modules["scheduler"] = f"healthy ({task_count} tasks)"
        else:
            modules["scheduler"] = "not_initialized"

    # Determine overall status
    unhealthy = [k for k, v in modules.items() if "unhealthy" in v]
    degraded = [k for k, v in modules.items() if "degraded" in v or "unreachable" in v]

    if unhealthy:
        overall = "unhealthy"
    elif degraded:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "version": settings.stone_config.get("stone", {}).get("version", "unknown"),
        "name": settings.stone_config.get("stone", {}).get("name", "STONE"),
        "uptime_seconds": int(uptime),
        "timestamp": datetime.utcnow().isoformat(),
        "modules": modules,
    }

"""
api/admin.py - Admin API endpoints for STONE (默行者)

All endpoints require authentication (whitelist + PIN or TOTP).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel

from config import DEFAULT_USER_ID
from models.errors import AuthError, StoneError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Auth Dependency ───────────────────────────────────────────────────────────

async def require_admin(
    request: Request,
    x_admin_pin: str | None = Header(default=None),
    x_open_id: str | None = Header(default=None),
) -> str:
    """
    Verify admin access via:
    1. Feishu open_id in whitelist (X-Open-Id header)
    2. Admin PIN (X-Admin-Pin header)

    Returns user_id on success.
    """
    loader = request.app.state.loader
    if loader is None:
        raise HTTPException(status_code=503, detail="System not initialized")

    open_id = x_open_id or ""
    if not loader.auth.verify_user(open_id):
        raise HTTPException(status_code=403, detail="Unauthorized: not in whitelist")

    if x_admin_pin:
        try:
            valid = await loader.auth.verify_pin(x_admin_pin, user_id=open_id)
            if not valid:
                raise HTTPException(status_code=403, detail="Invalid PIN")
        except AuthError as exc:
            raise HTTPException(status_code=403, detail=exc.message)

    return open_id or DEFAULT_USER_ID


# ── Task Schemas ──────────────────────────────────────────────────────────────

class CreateTaskRequest(BaseModel):
    name: str
    cron_expr: str
    action: str
    user_id: str = DEFAULT_USER_ID


class UpdateTaskRequest(BaseModel):
    enabled: bool | None = None


# ── Scheduled Tasks ───────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks(
    request: Request,
    user_id: str = DEFAULT_USER_ID,
    admin: str = Depends(require_admin),
) -> dict[str, Any]:
    loader = request.app.state.loader
    tasks = loader.scheduler.list_tasks(user_id)
    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "name": t.name,
                "cron_expr": t.cron_expr,
                "action": t.action,
                "enabled": t.enabled,
                "last_run": t.last_run.isoformat() if t.last_run else None,
                "created_at": t.created_at.isoformat(),
            }
            for t in tasks
        ],
        "total": len(tasks),
    }


@router.post("/tasks")
async def create_task(
    request: Request,
    body: CreateTaskRequest,
    admin: str = Depends(require_admin),
) -> dict[str, Any]:
    loader = request.app.state.loader
    try:
        task = await loader.scheduler.add_task(
            user_id=body.user_id,
            name=body.name,
            cron_expr=body.cron_expr,
            action=body.action,
        )
        return {
            "task_id": task.task_id,
            "name": task.name,
            "cron_expr": task.cron_expr,
            "created": True,
        }
    except StoneError as exc:
        raise HTTPException(status_code=400, detail=exc.message)


@router.put("/tasks/{task_id}")
async def update_task(
    request: Request,
    task_id: str,
    body: UpdateTaskRequest,
    user_id: str = DEFAULT_USER_ID,
    admin: str = Depends(require_admin),
) -> dict[str, Any]:
    loader = request.app.state.loader
    try:
        if body.enabled is True:
            await loader.scheduler.resume_task(user_id, task_id)
        elif body.enabled is False:
            await loader.scheduler.pause_task(user_id, task_id)
        return {"task_id": task_id, "updated": True}
    except StoneError as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@router.delete("/tasks/{task_id}")
async def delete_task(
    request: Request,
    task_id: str,
    user_id: str = DEFAULT_USER_ID,
    admin: str = Depends(require_admin),
) -> dict[str, Any]:
    loader = request.app.state.loader
    try:
        await loader.scheduler.delete_task(user_id, task_id)
        return {"task_id": task_id, "deleted": True}
    except StoneError as exc:
        raise HTTPException(status_code=404, detail=exc.message)


# ── Skills ────────────────────────────────────────────────────────────────────

@router.get("/skills")
async def list_skills(
    request: Request,
    admin: str = Depends(require_admin),
) -> dict[str, Any]:
    loader = request.app.state.loader
    skills = loader.skill_registry.list_tools()
    return {
        "skills": [
            {
                "name": s.name,
                "display_name": s.display_name,
                "description": s.description,
                "category": s.category.value,
                "enabled": s.enabled,
                "requires_confirmation": s.requires_confirmation,
                "phase": s.phase,
            }
            for s in skills
        ],
        "total": len(skills),
    }


# ── Audit Logs ────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_logs(
    request: Request,
    user_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    admin: str = Depends(require_admin),
) -> dict[str, Any]:
    loader = request.app.state.loader
    try:
        logs = await loader.sqlite_store.get_audit_logs(
            user_id=user_id, limit=limit, offset=offset
        )
        return {"logs": logs, "total": len(logs)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Memory ────────────────────────────────────────────────────────────────────

@router.get("/memory")
async def get_memory(
    request: Request,
    user_id: str = DEFAULT_USER_ID,
    category: str | None = None,
    limit: int = 50,
    admin: str = Depends(require_admin),
) -> dict[str, Any]:
    loader = request.app.state.loader
    try:
        from models.memory import MemoryCategory
        cat = MemoryCategory(category) if category else None
        memories = await loader.sqlite_store.get_memories(
            user_id=user_id, category=cat, limit=limit
        )
        return {
            "memories": [
                {
                    "memory_id": m.memory_id,
                    "category": m.category.value,
                    "content": m.content,
                    "confidence": m.confidence,
                    "tags": m.tags,
                    "created_at": m.created_at.isoformat(),
                    "access_count": m.access_count,
                }
                for m in memories
            ],
            "total": len(memories),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid category: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

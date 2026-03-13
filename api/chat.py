"""
api/chat.py - Chat API endpoints for STONE (默行者)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import DEFAULT_USER_ID
from models.errors import StoneError
from models.message import BotResponse, MessageSource, MessageType, UserMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


# ── Request / Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    content: str
    conv_id: str = ""
    user_id: str = DEFAULT_USER_ID
    task_type: str = "chat"
    privacy_sensitive: bool = False


class ConfirmRequest(BaseModel):
    action: str  # "confirm" | "cancel"
    user_id: str = DEFAULT_USER_ID


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=dict)
async def chat(request: Request, body: ChatRequest) -> dict[str, Any]:
    """
    Submit a message to the STONE agent and receive a response.

    For dry-run operations, the response will include:
    - requires_confirmation: true
    - confirmation_token: <conv_id>

    Use POST /api/chat/{conv_id}/confirm to confirm or cancel.
    """
    loader = _get_loader(request)

    msg = UserMessage(
        conv_id=body.conv_id or None,  # type: ignore[arg-type]
        user_id=body.user_id,
        message_type=MessageType.TEXT,
        source=MessageSource.API,
        content=body.content,
        task_type=body.task_type,
        privacy_sensitive=body.privacy_sensitive,
    )

    try:
        response: BotResponse = await loader.agent.process(msg)
    except StoneError as exc:
        logger.warning("Chat error: %s", exc.message)
        raise HTTPException(status_code=400, detail=exc.message)
    except Exception as exc:
        logger.exception("Unexpected chat error")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "response_id": response.response_id,
        "conv_id": response.conv_id,
        "content": response.content,
        "requires_confirmation": response.requires_confirmation,
        "confirmation_token": response.confirmation_token,
        "tools_used": response.tools_used,
        "is_error": response.is_error,
        "timestamp": response.timestamp.isoformat(),
    }


@router.get("/conversations/{conv_id}/history")
async def get_history(
    request: Request,
    conv_id: str,
    user_id: str = DEFAULT_USER_ID,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Retrieve the message history for a conversation.
    """
    loader = _get_loader(request)

    try:
        messages = await loader.sqlite_store.get_conversation_messages(
            conv_id=conv_id, limit=limit, offset=offset
        )
        conv = await loader.sqlite_store.get_conversation(conv_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "conv_id": conv_id,
        "conversation": conv,
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role.value,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
                "tool_name": m.tool_name,
            }
            for m in messages
        ],
        "total": len(messages),
    }


@router.post("/chat/{conv_id}/confirm")
async def confirm_dry_run(
    request: Request,
    conv_id: str,
    body: ConfirmRequest,
) -> dict[str, Any]:
    """
    Confirm or cancel a pending dry-run operation.

    Body:
        action: "confirm" | "cancel"
        user_id: user making the decision
    """
    loader = _get_loader(request)

    if body.action not in ("confirm", "cancel"):
        raise HTTPException(
            status_code=400,
            detail="action must be 'confirm' or 'cancel'",
        )

    if not loader.dry_run_manager.has_pending(conv_id):
        raise HTTPException(
            status_code=404,
            detail=f"No pending dry-run for conversation {conv_id}",
        )

    try:
        if body.action == "confirm":
            await loader.dry_run_manager.confirm(conv_id, user_id=body.user_id)
            return {"status": "confirmed", "conv_id": conv_id}
        else:
            await loader.dry_run_manager.cancel(conv_id, user_id=body.user_id)
            return {"status": "cancelled", "conv_id": conv_id}
    except StoneError as exc:
        raise HTTPException(status_code=400, detail=exc.message)


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_loader(request: Request) -> Any:
    loader = request.app.state.loader
    if loader is None:
        raise HTTPException(status_code=503, detail="System not initialized")
    return loader

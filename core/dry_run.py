"""
core/dry_run.py - Dry-run confirmation manager for STONE (默行者)

Generates human-readable operation previews, holds them pending user
confirmation, and records all decisions to the audit log.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from models.agent_state import ToolCall
from models.errors import DryRunRejectedError, StoneError

if TYPE_CHECKING:
    from security.audit import AuditLogger

logger = logging.getLogger(__name__)


class PendingPlan:
    """Internal state for a single pending dry-run confirmation."""

    def __init__(self, conv_id: str, plan: dict[str, Any]) -> None:
        self.conv_id = conv_id
        self.plan = plan
        self.created_at = datetime.utcnow()
        self.confirmed: bool | None = None
        self._event = asyncio.Event()

    def set_decision(self, confirmed: bool) -> None:
        self.confirmed = confirmed
        self._event.set()

    async def wait(self, timeout: float = 300.0) -> bool:
        """Wait for user decision. Returns True if confirmed, False if cancelled."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.confirmed = False
        return bool(self.confirmed)


class DryRunManager:
    """
    Manages pending operation previews that require user confirmation
    before the agent executes them.
    """

    def __init__(self, audit_logger: "AuditLogger | None" = None) -> None:
        self._pending: dict[str, PendingPlan] = {}
        self.audit_logger = audit_logger
        self._lock = asyncio.Lock()

    # ── Plan Generation ───────────────────────────────────────────────────────

    async def generate_plan(
        self,
        tool_calls: list[ToolCall],
        conv_id: str,
        user_message: str = "",
    ) -> dict[str, Any]:
        """
        Build a structured plan dict from a list of ToolCall objects and
        register it as pending confirmation.
        """
        steps = []
        for call in tool_calls:
            steps.append({
                "step": len(steps) + 1,
                "tool": call.tool_name,
                "params": call.params,
                "call_id": call.call_id,
            })

        plan: dict[str, Any] = {
            "conv_id": conv_id,
            "steps": steps,
            "total_steps": len(steps),
            "created_at": datetime.utcnow().isoformat(),
            "original_user_msg": user_message,
        }

        async with self._lock:
            self._pending[conv_id] = PendingPlan(conv_id=conv_id, plan=plan)

        logger.info("DryRun plan generated [conv=%s]: %d steps", conv_id, len(steps))
        return plan

    def format_preview(self, plan: dict[str, Any]) -> str:
        """
        Format a plan dict into a user-friendly Chinese Markdown message.
        """
        lines = [
            "⚠️ **操作预览 - 请确认**",
            "",
            f"本次操作共 **{plan.get('total_steps', 0)}** 步：",
            "",
        ]

        for step in plan.get("steps", []):
            tool = step.get("tool", "unknown")
            params = step.get("params", {})
            param_str = _format_params(tool, params)
            lines.append(f"**步骤 {step.get('step', '?')}** — `{tool}`")
            if param_str:
                lines.append(f"  参数：{param_str}")
            lines.append("")

        lines += [
            "---",
            "请回复：",
            "- `确认` 或 `/confirm` — 执行上述操作",
            "- `取消` 或 `/cancel`  — 放弃操作",
        ]

        return "\n".join(lines)

    # ── Confirmation / Cancellation ───────────────────────────────────────────

    async def confirm(self, conv_id: str, user_id: str = "default_user") -> None:
        """Mark the pending plan as confirmed."""
        async with self._lock:
            plan_obj = self._pending.get(conv_id)

        if plan_obj is None:
            raise StoneError(
                message=f"没有找到待确认的操作 (conv_id={conv_id})",
                code="DRY_RUN_NOT_FOUND",
            )

        plan_obj.set_decision(True)
        logger.info("DryRun confirmed [conv=%s] by user=%s", conv_id, user_id)

        if self.audit_logger:
            await self.audit_logger.log(
                level="INFO",
                action="dry_run_confirm",
                user_id=user_id,
                detail={"conv_id": conv_id, "decision": "confirm"},
                result="success",
            )

        async with self._lock:
            self._pending.pop(conv_id, None)

    async def cancel(self, conv_id: str, user_id: str = "default_user") -> None:
        """Mark the pending plan as cancelled."""
        async with self._lock:
            plan_obj = self._pending.get(conv_id)

        if plan_obj is None:
            raise StoneError(
                message=f"没有找到待取消的操作 (conv_id={conv_id})",
                code="DRY_RUN_NOT_FOUND",
            )

        plan_obj.set_decision(False)
        logger.info("DryRun cancelled [conv=%s] by user=%s", conv_id, user_id)

        if self.audit_logger:
            await self.audit_logger.log(
                level="WARNING",
                action="dry_run_cancel",
                user_id=user_id,
                detail={"conv_id": conv_id, "decision": "cancel"},
                result="blocked",
            )

        async with self._lock:
            self._pending.pop(conv_id, None)

    def has_pending(self, conv_id: str) -> bool:
        return conv_id in self._pending

    def get_pending_plan(self, conv_id: str) -> dict[str, Any] | None:
        plan_obj = self._pending.get(conv_id)
        return plan_obj.plan if plan_obj else None

    async def cleanup_expired(self, max_age_seconds: float = 600.0) -> int:
        """Remove stale pending plans older than max_age_seconds. Returns count removed."""
        now = datetime.utcnow()
        expired = []
        async with self._lock:
            for conv_id, plan_obj in self._pending.items():
                age = (now - plan_obj.created_at).total_seconds()
                if age > max_age_seconds:
                    expired.append(conv_id)
            for conv_id in expired:
                self._pending.pop(conv_id, None)

        if expired:
            logger.info("DryRun cleanup: removed %d expired plans", len(expired))
        return len(expired)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_params(tool: str, params: dict[str, Any]) -> str:
    """Return a short human-readable summary of tool parameters."""
    if not params:
        return ""
    if tool == "bash_tool":
        return f"`{params.get('command', '')}`"
    if tool == "file_tool":
        action = params.get("action", "")
        path = params.get("path", "")
        return f"action={action}, path=`{path}`"
    if tool == "search_tool":
        return f"query=`{params.get('query', '')}`"
    # Generic fallback
    parts = [f"{k}=`{v}`" for k, v in list(params.items())[:3]]
    return ", ".join(parts)


__all__ = ["DryRunManager", "PendingPlan"]

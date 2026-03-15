"""
core/scheduler.py - APScheduler-based task scheduler for STONE (默行者)

Persists scheduled tasks to SQLite and restores them on startup.
Tasks are executed by calling agent.process() with a synthetic UserMessage.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any  # noqa: F401

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import]

from models.errors import StoneError
from modules.interfaces.scheduler import SchedulerInterface

if TYPE_CHECKING:
    from core.agent import Agent
    from modules.memory.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class ScheduledTask:
    """In-memory representation of a scheduled task."""

    def __init__(
        self,
        task_id: str,
        user_id: str,
        name: str,
        cron_expr: str,
        action: str,
        enabled: bool = True,
    ) -> None:
        self.task_id = task_id
        self.user_id = user_id
        self.name = name
        self.cron_expr = cron_expr
        self.action = action
        self.enabled = enabled
        self.created_at = datetime.utcnow()
        self.last_run: datetime | None = None


class Scheduler(SchedulerInterface):
    """
    Wraps APScheduler with STONE-specific task management and SQLite persistence.
    """

    def __init__(self, sqlite_store: "SQLiteStore", agent: "Agent | None" = None) -> None:
        self.sqlite_store = sqlite_store
        self.agent = agent
        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._tasks: dict[str, ScheduledTask] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the scheduler and restore persisted tasks."""
        self._scheduler.start()
        await self._restore_tasks()
        logger.info("Scheduler started with %d restored tasks", len(self._tasks))

    async def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    # ── Task Management ───────────────────────────────────────────────────────

    async def add_task(
        self,
        user_id: str,
        name: str,
        cron_expr: str,
        action: str,
    ) -> ScheduledTask:
        """
        Create and persist a new scheduled task.

        Args:
            user_id:   Owner of the task.
            name:      Human-readable task name.
            cron_expr: Standard cron expression, e.g. "0 9 * * 1-5".
            action:    The message/command to send to the agent when triggered.
        """
        _validate_cron(cron_expr)

        task_id = str(uuid.uuid4())
        task = ScheduledTask(
            task_id=task_id,
            user_id=user_id,
            name=name,
            cron_expr=cron_expr,
            action=action,
        )

        self._tasks[task_id] = task
        self._schedule_apscheduler_job(task)

        await self.sqlite_store.save_scheduled_task(
            task_id=task_id,
            user_id=user_id,
            name=name,
            cron_expr=cron_expr,
            action=action,
        )

        logger.info("Scheduled task added: %s (%s) [user=%s]", name, cron_expr, user_id)
        return task

    def list_tasks(self, user_id: str) -> list[ScheduledTask]:
        """Return all tasks owned by user_id."""
        return [t for t in self._tasks.values() if t.user_id == user_id]

    async def pause_task(self, user_id: str, task_id: str) -> None:
        """Pause a task without deleting it."""
        task = self._get_task(user_id, task_id)
        task.enabled = False
        self._scheduler.pause_job(task_id)
        await self.sqlite_store.update_scheduled_task_enabled(task_id, enabled=False)
        logger.info("Task %s paused", task_id)

    async def resume_task(self, user_id: str, task_id: str) -> None:
        """Resume a previously paused task."""
        task = self._get_task(user_id, task_id)
        task.enabled = True
        self._scheduler.resume_job(task_id)
        await self.sqlite_store.update_scheduled_task_enabled(task_id, enabled=True)
        logger.info("Task %s resumed", task_id)

    async def delete_task(self, user_id: str, task_id: str) -> None:
        """Permanently remove a task."""
        task = self._get_task(user_id, task_id)
        try:
            self._scheduler.remove_job(task_id)
        except Exception:
            pass
        del self._tasks[task_id]
        await self.sqlite_store.delete_scheduled_task(task_id)
        logger.info("Task %s deleted [user=%s]", task_id, user_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_task(self, user_id: str, task_id: str) -> ScheduledTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise StoneError(
                message=f"任务未找到: {task_id}",
                code="TASK_NOT_FOUND",
            )
        if task.user_id != user_id:
            raise StoneError(
                message="无权操作此任务",
                code="TASK_PERMISSION_DENIED",
            )
        return task

    def _schedule_apscheduler_job(self, task: ScheduledTask) -> None:
        trigger = CronTrigger.from_crontab(task.cron_expr, timezone="Asia/Shanghai")
        self._scheduler.add_job(
            func=self._execute_task,
            trigger=trigger,
            id=task.task_id,
            name=task.name,
            args=[task.task_id],
            replace_existing=True,
        )

    async def _execute_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or not task.enabled:
            return

        logger.info("Executing scheduled task %s: %s", task_id, task.name)
        task.last_run = datetime.utcnow()

        if self.agent is None:
            logger.warning("Scheduler: agent not set, cannot execute task %s", task_id)
            return

        from models.message import MessageSource, MessageType, UserMessage

        msg = UserMessage(
            conv_id=str(uuid.uuid4()),
            user_id=task.user_id,
            message_type=MessageType.COMMAND,
            source=MessageSource.INTERNAL,
            content=task.action,
        )

        try:
            await self.agent.process(msg)
        except Exception as exc:
            logger.exception("Scheduled task %s failed: %s", task_id, exc)

        await self.sqlite_store.update_scheduled_task_last_run(task_id, task.last_run)

    def register_memory_tasks(self, memory_store: Any, memory_extractor: Any) -> None:
        """
        Register built-in system tasks for forgetting-curve decay and weekly
        user-profile generation. Called from loader after all components are ready.
        """
        # Daily decay at 03:00 (all active users)
        self._scheduler.add_job(
            func=self._run_memory_decay,
            trigger=CronTrigger(hour=3, minute=0, timezone="Asia/Shanghai"),
            id="__system_memory_decay__",
            name="记忆遗忘曲线衰减（每日）",
            args=[memory_store],
            replace_existing=True,
        )
        # Weekly profile at Sunday 04:00
        self._scheduler.add_job(
            func=self._run_weekly_profile,
            trigger=CronTrigger(day_of_week="sun", hour=4, minute=0, timezone="Asia/Shanghai"),
            id="__system_weekly_profile__",
            name="用户画像生成（每周）",
            args=[memory_store, memory_extractor],
            replace_existing=True,
        )
        logger.info("Memory system tasks registered (daily decay + weekly profile)")

    async def _run_memory_decay(self, memory_store: Any) -> None:
        """Run forgetting-curve decay for all active users."""
        try:
            user_ids = await memory_store.list_active_users()
            total = {"updated": 0, "compressed": 0, "forgotten": 0}
            for uid in user_ids:
                stats = await memory_store.run_decay(uid)
                for k in total:
                    total[k] += stats.get(k, 0)
            logger.info("Memory decay done: %s", total)
        except Exception as exc:
            logger.exception("Memory decay task failed: %s", exc)

    async def _run_weekly_profile(self, memory_store: Any, memory_extractor: Any) -> None:
        """Generate weekly user profile for all active users."""
        try:
            user_ids = await memory_store.list_active_users()
            for uid in user_ids:
                profile = await memory_extractor.generate_user_profile(uid)
                if profile:
                    logger.info("Weekly profile generated for user %s", uid[:12])
        except Exception as exc:
            logger.exception("Weekly profile task failed: %s", exc)

    async def _restore_tasks(self) -> None:
        """Load tasks from SQLite and re-schedule them."""
        try:
            rows = await self.sqlite_store.get_all_scheduled_tasks()
        except Exception as exc:
            logger.warning("Failed to restore scheduled tasks: %s", exc)
            return

        for row in rows:
            task = ScheduledTask(
                task_id=row["task_id"],
                user_id=row["user_id"],
                name=row["name"],
                cron_expr=row["cron_expr"],
                action=row["action"],
                enabled=bool(row.get("enabled", 1)),
            )
            self._tasks[task.task_id] = task
            if task.enabled:
                try:
                    self._schedule_apscheduler_job(task)
                except Exception as exc:
                    logger.warning("Failed to restore task %s: %s", task.task_id, exc)


def _validate_cron(expr: str) -> None:
    """Raise StoneError if the cron expression is invalid."""
    try:
        CronTrigger.from_crontab(expr)
    except Exception as exc:
        raise StoneError(
            message=f"无效的 cron 表达式 {expr!r}: {exc}",
            code="INVALID_CRON",
        ) from exc


__all__ = ["Scheduler", "ScheduledTask"]

"""
modules/interfaces/scheduler.py - Task scheduler interface.

Built-in drivers:
  apscheduler → core.scheduler.Scheduler  (Phase 1, default)

Third-party alternatives:
  celery      → core.scheduler_celery.CeleryScheduler   (future)
  rq          → core.scheduler_rq.RQScheduler            (future)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SchedulerInterface(ABC):
    """
    Contract for scheduled task management.

    Handles cron-expression based tasks that invoke the agent.
    Implementations must persist tasks across restarts.
    """

    @abstractmethod
    async def start(self) -> None:
        """Start the scheduler background loop."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the scheduler."""
        ...

    @abstractmethod
    async def add_task(
        self,
        user_id: str,
        name: str,
        cron_expr: str,
        action: str,
    ) -> Any:
        """
        Schedule a new task.

        Args:
            user_id:   Owner of the task.
            name:      Short human-readable name.
            cron_expr: Standard 5-field cron expression (e.g. "0 8 * * *").
            action:    Natural-language instruction passed to the agent.

        Returns:
            A task object with at least a `.task_id` attribute.
        """
        ...

    @abstractmethod
    async def delete_task(self, user_id: str, task_id: str) -> None:
        """Remove a scheduled task. Raises StoneError if not owned by user."""
        ...

    @abstractmethod
    def list_tasks(self, user_id: str | None = None) -> list[Any]:
        """
        Return all scheduled tasks, optionally filtered by user.

        Returns:
            List of task objects.
        """
        ...


__all__ = ["SchedulerInterface"]

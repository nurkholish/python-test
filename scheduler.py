"""Simple scheduler: run all tasks whose HH:MM matches the current clock."""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Callable, Iterable, Sequence

from executor import ExecutionResult, TaskExecutor
from task import Task

logger = logging.getLogger(__name__)

TIME_FMT = "%H:%M"

Clock = Callable[[], _dt.datetime]


class Scheduler:
    """Owns the task list and the clock; delegates execution to TaskExecutor.

    The clock is injectable so tests and demos are deterministic.
    """

    def __init__(
        self,
        executor: TaskExecutor,
        clock: Clock | None = None,
    ) -> None:
        self._executor = executor
        self._clock: Clock = clock or _dt.datetime.now
        self._tasks: list[Task] = []

    # --- task management --------------------------------------------------
    def add_task(self, task: Task) -> None:
        self._tasks.append(task)
        logger.debug(
            "Registered task %s for %s at %s",
            task.id or "-",
            task.user,
            task.time,
        )

    def add_tasks(self, tasks: Iterable[Task]) -> None:
        for task in tasks:
            self.add_task(task)

    # --- run --------------------------------------------------------------
    def run_once(self) -> Sequence[ExecutionResult]:
        """Execute every task scheduled for the current minute, in order."""
        now = self._clock().strftime(TIME_FMT)
        due = [t for t in self._tasks if t.time == now]
        logger.info("Scheduler tick %s: %d task(s) due", now, len(due))
        return [self._executor.execute(task) for task in due]
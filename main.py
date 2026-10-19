"""Application entry point.

Run with:

    python main.py

Uses bare imports so it works both as a script and inside a flat repo.
"""
from __future__ import annotations

import datetime as dt
import logging

from executor import TaskExecutor
from logging_config import configure_logging
from scheduler import Scheduler
from task import Task
from user_manager import UserManager

logger = logging.getLogger(__name__)


def build_scheduler(
    users: UserManager | None = None,
    clock=None,
) -> Scheduler:
    """Wire UserManager → TaskExecutor → Scheduler."""
    users = users or UserManager()
    return Scheduler(TaskExecutor(users), clock=clock)


def demo(now: dt.datetime | None = None) -> None:
    """Run the sample scenario (Alice + Bob at 12:00)."""
    configure_logging(level=logging.INFO)

    users = UserManager()
    users.add_user("alice", quota=3)
    users.add_user("bob", quota=5)

    fixed_now = now or dt.datetime(2024, 1, 1, 12, 0)
    scheduler = build_scheduler(users, clock=lambda: fixed_now)

    scheduler.add_tasks(
        [
            Task(
                user="alice",
                time="12:00",
                action="sync",
                target="/data/x",
                params={"mode": "incremental"},
                id="a-sync",
            ),
            Task(
                user="bob",
                time="12:00",
                action="backup",
                target="/srv/y",
                params={"compress": True},
                id="b-backup",
            ),
            # Second task for alice in the same minute — shows multi-task support.
            Task(
                user="alice",
                time="12:00",
                action="delete",
                target="/tmp/z",
                id="a-delete",
            ),
        ]
    )

    results = scheduler.run_once()

    logger.info("Summary: %s", users.snapshot())
    for r in results:
        logger.info("result id=%s status=%s", r.task.id or "-", r.status.value)


if __name__ == "__main__":
    demo()
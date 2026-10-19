"""Task execution: quota enforcement + extensible action strategies.

Supports two registration styles:

1. **Function handlers** (existing) — ``Callable[[str, Mapping], str]``.
2. **OOP strategies** — subclasses of :class:`ActionStrategy` (or any object
   with a matching ``__call__``).

Both are equivalent at call time, so no existing code needs to change.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from task import Task
from user_manager import UnknownUserError, UserManager

logger = logging.getLogger(__name__)


class Status(str, Enum):
    """Outcome of a single task execution."""

    EXECUTED = "executed"
    QUOTA_EXCEEDED = "quota_exceeded"
    UNKNOWN_USER = "unknown_user"
    UNKNOWN_ACTION = "unknown_action"
    FAILED = "failed"


@dataclass(frozen=True)
class ExecutionResult:
    task: Task
    status: Status
    detail: str = ""


# --- Extensibility: strategy protocol --------------------------------------
@runtime_checkable
class ActionStrategy(Protocol):
    """Structural protocol for action handlers.

    Any object with this ``__call__`` signature is a valid strategy —
    plain functions and lambdas included.
    """

    def __call__(self, target: str, params: Mapping[str, Any]) -> str:
        ...


ActionHandler = ActionStrategy  # backward-compatible alias


# --- OOP strategies (optional, additive) -----------------------------------
class BaseStrategy:
    """Convenience base class for OOP strategies.

    Subclasses set ``name`` and override :meth:`perform`.
    """

    name: str = ""

    def __call__(self, target: str, params: Mapping[str, Any]) -> str:
        logger.debug("Strategy %r invoked: target=%s params=%s",
                     self.name, target, dict(params))
        return self.perform(target, params)

    def perform(self, target: str, params: Mapping[str, Any]) -> str:  # pragma: no cover
        raise NotImplementedError


class SyncStrategy(BaseStrategy):
    name = "sync"

    def perform(self, target: str, params: Mapping[str, Any]) -> str:
        suffix = f" params={dict(params)}" if params else ""
        print(f"Executing sync on {target}{suffix}")
        return f"sync:{target}"


class BackupStrategy(BaseStrategy):
    name = "backup"

    def perform(self, target: str, params: Mapping[str, Any]) -> str:
        suffix = f" params={dict(params)}" if params else ""
        print(f"Executing backup on {target}{suffix}")
        return f"backup:{target}"


class DeleteStrategy(BaseStrategy):
    name = "delete"

    def perform(self, target: str, params: Mapping[str, Any]) -> str:
        suffix = f" params={dict(params)}" if params else ""
        print(f"Executing delete on {target}{suffix}")
        return f"delete:{target}"


# --- Executor ---------------------------------------------------------------
class TaskExecutor:
    """Executes a single task, enforcing quota and dispatching by action.

    Handlers may be plain callables or :class:`BaseStrategy` subclasses;
    both are stored as ``ActionStrategy`` and invoked identically.
    """

    def __init__(self, user_manager: UserManager) -> None:
        self._users = user_manager
        self._handlers: dict[str, ActionHandler] = {}
        self._register_default_handlers()

    # --- handler registration --------------------------------------------
    def register_action(self, name: str, handler: ActionHandler) -> None:
        if not name:
            raise ValueError("action name must be non-empty")
        if not callable(handler):
            raise TypeError(
                f"handler for {name!r} must be callable, got {type(handler).__name__}"
            )
        self._handlers[name] = handler
        logger.debug("Registered action handler %r", name)

    def _register_default_handlers(self) -> None:
        self.register_action("sync",   SyncStrategy())
        self.register_action("backup", BackupStrategy())
        self.register_action("delete", DeleteStrategy())

    # --- execution --------------------------------------------------------
    def execute(self, task: Task) -> ExecutionResult:
        task_id = task.id or "-"

        try:
            self._users.get(task.user)
        except UnknownUserError:
            detail = f"unknown user {task.user!r}"
            logger.warning("Skipping task %s: %s", task_id, detail)
            return ExecutionResult(task, Status.UNKNOWN_USER, detail)

        if not self._users.has_capacity(task.user):
            detail = f"{task.user} has exceeded quota."
            logger.info(detail)
            return ExecutionResult(task, Status.QUOTA_EXCEEDED, detail)

        handler = self._handlers.get(task.action)
        if handler is None:
            detail = f"unknown action {task.action!r}"
            logger.error("Skipping task %s: %s", task_id, detail)
            return ExecutionResult(task, Status.UNKNOWN_ACTION, detail)

        try:
            detail = handler(task.target, task.params)
        except Exception as exc:  # noqa: BLE001 — never crash the scheduler
            logger.exception("Task %s failed", task_id)
            return ExecutionResult(task, Status.FAILED, str(exc))

        self._users.consume(task.user)
        logger.info(
            "Executed task %s (%s -> %s) for %s",
            task_id, task.action, task.target, task.user,
        )
        return ExecutionResult(task, Status.EXECUTED, detail)
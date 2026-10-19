"""Task domain model: immutable, validated, with configurable parameters."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Mapping

TIME_FMT = "%H:%M"


class TaskValidationError(ValueError):
    """Raised when a task payload is malformed."""


@dataclass(frozen=True, slots=True)
class Task:
    """A single scheduled job.

    Attributes:
        user:    owner of the task (must exist in ``UserManager``).
        time:    scheduled time in ``HH:MM`` 24-hour format.
        action:  registered action name (``sync``, ``backup``, ``delete``, ...).
        target:  opaque destination the action operates on.
        params:  free-form extra configuration passed to the action handler.
        id:      optional stable identifier (useful for logging / dedupe).
    """

    user: str
    time: str
    action: str
    target: str
    params: Mapping[str, Any] = field(default_factory=dict)
    id: str | None = None

    def __post_init__(self) -> None:
        if not self.user:
            raise TaskValidationError("task.user must be non-empty")
        if not self.action:
            raise TaskValidationError("task.action must be non-empty")
        try:
            _dt.datetime.strptime(self.time, TIME_FMT)
        except (TypeError, ValueError) as exc:
            raise TaskValidationError(
                f"task.time must match {TIME_FMT!r}, got {self.time!r}"
            ) from exc

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Task":
        """Build a Task from a raw mapping (e.g. YAML/JSON payload)."""
        try:
            return cls(
                user=payload["user"],
                time=payload["time"],
                action=payload["action"],
                target=payload["target"],
                params=dict(payload.get("params", {})),
                id=payload.get("id"),
            )
        except KeyError as exc:
            raise TaskValidationError(f"missing field: {exc.args[0]}") from exc
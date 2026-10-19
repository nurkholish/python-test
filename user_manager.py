"""User registry with per-user quotas and execution counters."""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class UnknownUserError(KeyError):
    """Raised when a task references a user that is not registered."""


@dataclass
class UserState:
    """Mutable per-user state: quota + executions consumed so far."""

    quota: int
    executed: int = 0

    def has_capacity(self) -> bool:
        return self.executed < self.quota

    def record_execution(self) -> None:
        self.executed += 1


class UserManager:
    """Registry + quota enforcement for users.

    Not thread-safe by design (single-writer scheduler).  If you introduce
    concurrency, guard mutations with a ``threading.Lock``.
    """

    def __init__(self) -> None:
        self._users: dict[str, UserState] = {}

    # --- registration -----------------------------------------------------
    def add_user(self, name: str, quota: int) -> None:
        if not name:
            raise ValueError("user name must be non-empty")
        if quota < 0:
            raise ValueError(f"quota must be >= 0, got {quota}")
        if name in self._users:
            logger.warning("Overwriting existing user %r", name)
        self._users[name] = UserState(quota=quota)
        logger.debug("Registered user %r with quota=%d", name, quota)

    # --- lookup -----------------------------------------------------------
    def get(self, name: str) -> UserState:
        try:
            return self._users[name]
        except KeyError as exc:
            raise UnknownUserError(name) from exc

    def __contains__(self, name: object) -> bool:
        return name in self._users

    # --- quota ------------------------------------------------------------
    def has_capacity(self, name: str) -> bool:
        return self.get(name).has_capacity()

    def consume(self, name: str) -> None:
        """Increment ``executed``; caller MUST have checked capacity first."""
        state = self.get(name)
        state.record_execution()
        logger.debug(
            "User %r executed=%d/%d", name, state.executed, state.quota
        )

    def snapshot(self) -> dict[str, dict[str, int]]:
        """Read-only copy — handy for reporting and tests."""
        return {
            name: {"quota": s.quota, "executed": s.executed}
            for name, s in self._users.items()
        }
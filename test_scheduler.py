"""Run with:  python -m pytest -q test_scheduler.py  (from pyton-test/)."""
from __future__ import annotations

import datetime as dt

import pytest

from executor import Status, TaskExecutor
from scheduler import Scheduler
from task import Task, TaskValidationError
from user_manager import UnknownUserError, UserManager


def _clock(hour: int, minute: int):
    return lambda: dt.datetime(2024, 1, 1, hour, minute)


@pytest.fixture
def users() -> UserManager:
    um = UserManager()
    um.add_user("alice", quota=1)
    um.add_user("bob", quota=5)
    return um


def test_task_rejects_bad_time():
    with pytest.raises(TaskValidationError):
        Task(user="a", time="9:00", action="sync", target="/x")


def test_task_from_dict_roundtrip():
    t = Task.from_dict(
        {
            "user": "a",
            "time": "12:00",
            "action": "sync",
            "target": "/x",
            "params": {"k": 1},
            "id": "t1",
        }
    )
    assert t.params == {"k": 1}
    assert t.id == "t1"


def test_executes_matching_tasks(users):
    sched = Scheduler(TaskExecutor(users), clock=_clock(12, 0))
    sched.add_task(Task(user="alice", time="12:00", action="sync", target="/a"))
    results = sched.run_once()
    assert [r.status for r in results] == [Status.EXECUTED]
    assert users.get("alice").executed == 1


def test_multiple_tasks_same_user_quota_enforced(users):
    sched = Scheduler(TaskExecutor(users), clock=_clock(12, 0))
    sched.add_tasks(
        [
            Task(user="alice", time="12:00", action="sync", target="/a", id="1"),
            Task(user="alice", time="12:00", action="delete", target="/b", id="2"),
        ]
    )
    statuses = [r.status for r in sched.run_once()]
    assert statuses == [Status.EXECUTED, Status.QUOTA_EXCEEDED]
    assert users.get("alice").executed == 1


def test_configurable_params_reach_handler(users):
    seen: dict = {}
    ex = TaskExecutor(users)
    ex.register_action(
        "sync", lambda target, params: seen.update(t=target, p=params) or "ok"
    )
    r = ex.execute(
        Task(
            user="alice",
            time="12:00",
            action="sync",
            target="/a",
            params={"mode": "full"},
        )
    )
    assert r.status is Status.EXECUTED
    assert seen == {"t": "/a", "p": {"mode": "full"}}


def test_unknown_user_does_not_raise(users):
    r = TaskExecutor(users).execute(
        Task(user="eve", time="12:00", action="sync", target="/a")
    )
    assert r.status is Status.UNKNOWN_USER


def test_unknown_action_does_not_raise(users):
    r = TaskExecutor(users).execute(
        Task(user="alice", time="12:00", action="nope", target="/a")
    )
    assert r.status is Status.UNKNOWN_ACTION


def test_handler_exception_is_contained(users):
    ex = TaskExecutor(users)
    ex.register_action(
        "boom", lambda t, p: (_ for _ in ()).throw(RuntimeError("x"))
    )
    r = ex.execute(
        Task(user="alice", time="12:00", action="boom", target="/a")
    )
    assert r.status is Status.FAILED
    assert users.get("alice").executed == 0


def test_wrong_minute_skipped(users):
    sched = Scheduler(TaskExecutor(users), clock=_clock(12, 0))
    sched.add_task(
        Task(user="alice", time="09:00", action="sync", target="/a")
    )
    assert sched.run_once() == []


def test_unknown_user_lookup_raises(users):
    with pytest.raises(UnknownUserError):
        users.get("ghost")
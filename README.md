# Task Scheduler

A small, dependency-free, class-based task scheduler written in pure Python
(3.9+). Tasks are scheduled per minute; execution is governed by per-user
quotas; every decision is logged; and action handlers are pluggable via both
plain callables and OOP strategy classes.

---

## Table of Contents

- [Features](#features)
- [Project Layout](#project-layout)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Modules](#modules)
  - [`logging_config.py`](#logging_configpy)
  - [`task.py`](#taskpy)
  - [`user_manager.py`](#user_managerpy)
  - [`executor.py`](#executorpy)
  - [`scheduler.py`](#schedulerpy)
  - [`main.py`](#mainpy)
- [Usage Examples](#usage-examples)
  - [Run the demo](#run-the-demo)
  - [Custom action via lambda](#custom-action-via-lambda)
  - [Custom action via OOP strategy](#custom-action-via-oop-strategy)
  - [Multiple tasks per user](#multiple-tasks-per-user)
  - [Configurable task parameters](#configurable-task-parameters)
  - [Deterministic clock](#deterministic-clock)
- [Execution Flow](#execution-flow)
- [Status Codes](#status-codes)
- [Logging](#logging)
- [Testing](#testing)
- [Design Notes](#design-notes)
- [Extending the System](#extending-the-system)
- [Behaviour Parity with Original Script](#behaviour-parity-with-original-script)

---

## Features

- **Class-based, modular design** — one class per responsibility, five focused modules.
- **User management & quota control** — per-user execution quotas enforced before dispatch.
- **Immutable, validated task model** — `Task` dataclass with `__post_init__` validation and a `from_dict` factory.
- **Extensible executor** — register actions as plain callables **or** `BaseStrategy` subclasses.
- **Simple scheduler** — filters tasks by current minute (`HH:MM`) and delegates execution.
- **Multiple tasks per user** — tasks are a flat list; nothing prevents one user from owning many tasks.
- **Configurable task parameters** — `Task.params: Mapping[str, Any]` forwarded verbatim to handlers.
- **Structured results** — every execution yields an `ExecutionResult(task, status, detail)`.
- **Full logging** — `logging` at every decision point (`scheduler`, `executor`, `user_manager`).
- **Testable by construction** — clock, executor, and user manager are all injectable.
- **No external dependencies** — standard library only.

---

## Project Layout

```
pyton-test/
├── logging_config.py     # centralised logging setup
├── task.py               # Task dataclass + validation
├── user_manager.py       # UserManager, UserState, quota control
├── executor.py           # TaskExecutor, Status, ActionStrategy
├── scheduler.py          # Scheduler
├── main.py               # entry point + demo
├── test_scheduler.py     # pytest suite (optional)
└── README.md             # this file
```

Run with:

```bash
cd pyton-test
python main.py
```

---

## Requirements

- Python **3.9+** (uses `list[str]`, `X | None`, `slots=True` — all available in 3.9 / 3.10; the `slots=True` dataclass flag requires 3.10, so **3.10+** for `Task`).
- No third-party runtime dependencies.
- `pytest` is only needed for the test suite (`pip install pytest`).

---

## Quick Start

```bash
python main.py
```

Expected output (timestamps vary; ordering of `print` and `INFO` lines may
interleave because stdout and stderr are separate streams):

```
2026-10-19 16:24:46,864 [INFO] scheduler: Scheduler tick 12:00: 3 task(s) due
Executing sync on /data/x params={'mode': 'incremental'}
2026-10-19 16:24:46,864 [INFO] executor: Executed task a-sync (sync -> /data/x) for alice
Executing backup on /srv/y params={'compress': True}
2026-10-19 16:24:46,865 [INFO] executor: Executed task b-backup (backup -> /srv/y) for bob
Executing delete on /tmp/z
2026-10-19 16:24:46,865 [INFO] executor: Executed task a-delete (delete -> /tmp/z) for alice
2026-10-19 16:24:46,865 [INFO] __main__: Summary: {'alice': {'quota': 3, 'executed': 2}, 'bob': {'quota': 5, 'executed': 1}}
2026-10-19 16:24:46,865 [INFO] __main__: result id=a-sync status=executed
2026-10-19 16:24:46,865 [INFO] __main__: result id=b-backup status=executed
2026-10-19 16:24:46,865 [INFO] __main__: result id=a-delete status=executed
```

To merge stdout and stderr into one ordered stream:

```bash
python main.py 2>&1
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Scheduler                            │
│  owns clock + task list; filters by HH:MM, delegates    │
└───────────────┬─────────────────────┬───────────────────┘
                │                     │
      ┌─────────▼─────────┐  ┌────────▼──────────┐
      │   Task model      │  │  UserManager      │
      │  (frozen dataclass│  │  (registry,       │
      │   + validation)   │  │   quota state)    │
      └───────────────────┘  └────────┬──────────┘
                                      │
                            ┌─────────▼─────────┐
                            │  TaskExecutor     │
                            │  (strategy map,   │
                            │   quota gate)     │
                            └───────────────────┘
```

**Separation of concerns**

| Concern | Owner |
|---|---|
| When to run | `Scheduler` (clock injection) |
| What to run | `Task` (data model) |
| Who may run | `UserManager` (quota) |
| How to run | `TaskExecutor` + `ActionStrategy` |
| Visibility | `logging` in every module |

---

## Modules

### `logging_config.py`

Idempotent logging setup shared across all modules.

```python
def configure_logging(level: int = logging.INFO, fmt: str = _DEFAULT_FORMAT) -> None
```

If the root logger already has handlers (e.g. embedded in a larger app),
only the level is adjusted — safe to call multiple times.

---

### `task.py`

The task domain model.

```python
@dataclass(frozen=True, slots=True)
class Task:
    user: str
    time: str                                    # "HH:MM"
    action: str
    target: str
    params: Mapping[str, Any] = field(default_factory=dict)
    id: str | None = None
```

**Validation** (`__post_init__`):

- `user` non-empty
- `action` non-empty
- `time` matches `"%H:%M"` → raises `TaskValidationError` otherwise

**Factory**:

```python
Task.from_dict({"user": "alice", "time": "12:00", "action": "sync",
                "target": "/x", "params": {"mode": "full"}, "id": "t1"})
```

Missing required keys raise `TaskValidationError`.

---

### `user_manager.py`

Per-user quota registry.

```python
@dataclass
class UserState:
    quota: int
    executed: int = 0
    def has_capacity(self) -> bool: ...
    def record_execution(self) -> None: ...

class UserManager:
    def add_user(self, name: str, quota: int) -> None: ...
    def get(self, name: str) -> UserState: ...          # raises UnknownUserError
    def has_capacity(self, name: str) -> bool: ...
    def consume(self, name: str) -> None: ...
    def snapshot(self) -> dict[str, dict[str, int]]: ...
```

**Rules**

- `quota >= 0`, name non-empty (`ValueError` otherwise)
- Re-adding an existing user logs a warning and overwrites
- `consume()` must be called only after `has_capacity()` returns `True`
- **Not thread-safe** — single-writer scheduler by design

---

### `executor.py`

Task execution with quota gating and a pluggable strategy registry.

**`Status`** (str Enum): `EXECUTED`, `QUOTA_EXCEEDED`, `UNKNOWN_USER`,
`UNKNOWN_ACTION`, `FAILED`.

**`ExecutionResult`**:

```python
@dataclass(frozen=True)
class ExecutionResult:
    task: Task
    status: Status
    detail: str = ""
```

**`ActionStrategy`** (Protocol) — any callable with signature
`(target: str, params: Mapping[str, Any]) -> str` satisfies it. Plain
functions, lambdas, and `BaseStrategy` subclasses are all valid.

**`BaseStrategy`** — convenience base for OOP strategies:

```python
class BaseStrategy:
    name: str = ""
    def __call__(self, target, params) -> str:   # delegates to perform()
        ...
    def perform(self, target, params) -> str:    # override this
        raise NotImplementedError
```

**Bundled strategies**: `SyncStrategy`, `BackupStrategy`, `DeleteStrategy`.

**`TaskExecutor`**:

```python
def __init__(self, user_manager: UserManager) -> None
def register_action(self, name: str, handler: ActionHandler) -> None
def execute(self, task: Task) -> ExecutionResult
```

`register_action` accepts both lambdas and `BaseStrategy` instances. It
raises `TypeError` for non-callables and `ValueError` for empty names.

**Execution order in `execute()`** (deliberately ordered to preserve
original semantics):

1. Unknown user → `UNKNOWN_USER` (no exception, logged warning)
2. Quota exceeded → `QUOTA_EXCEEDED` (logged info)
3. Unknown action → `UNKNOWN_ACTION` (logged error)
4. Handler raises → `FAILED` (logged exception, counter **not** consumed)
5. Otherwise → `EXECUTED` (counter consumed, logged info)

---

### `scheduler.py`

Minimal per-minute scheduler.

```python
class Scheduler:
    def __init__(self, executor: TaskExecutor, clock: Callable[[], datetime] | None = None)
    def add_task(self, task: Task) -> None
    def add_tasks(self, tasks: Iterable[Task]) -> None
    def run_once(self) -> Sequence[ExecutionResult]
```

`run_once()` stringifies `clock()` to `"%H:%M"`, filters tasks with a
matching `time`, executes them in registration order, and returns the
list of `ExecutionResult`. Tasks with non-matching times are silently
skipped (logged at DEBUG).

---

### `main.py`

Entry point + demo.

```python
def build_scheduler(users: UserManager | None = None, clock=None) -> Scheduler
def demo(now: datetime | None = None) -> None
```

The demo registers Alice (quota 3) with two tasks and Bob (quota 5) with
one, pins the clock to `2024-01-01 12:00`, and runs a single tick.

---

## Usage Examples

### Run the demo

```bash
python main.py
```

### Custom action via lambda

```python
from executor import TaskExecutor
from task import Task
from user_manager import UserManager

users = UserManager()
users.add_user("alice", quota=3)

executor = TaskExecutor(users)
executor.register_action(
    "ping",
    lambda target, params: print(f"ping {target}") or f"ping:{target}",
)

result = executor.execute(
    Task(user="alice", time="12:00", action="ping", target="host-1")
)
print(result.status)  # Status.EXECUTED
```

### Custom action via OOP strategy

```python
from executor import BaseStrategy, TaskExecutor
from task import Task
from user_manager import UserManager

class UploadStrategy(BaseStrategy):
    name = "upload"

    def perform(self, target, params):
        bucket = params.get("bucket", "default")
        print(f"Uploading {target} to s3://{bucket}")
        return f"upload:{target}->{bucket}"

users = UserManager()
users.add_user("alice", quota=3)
executor = TaskExecutor(users)
executor.register_action("upload", UploadStrategy())

result = executor.execute(
    Task(user="alice", time="12:00", action="upload",
         target="/data/file.bin", params={"bucket": "backups"})
)
```

### Multiple tasks per user

```python
from scheduler import Scheduler
from task import Task
from executor import TaskExecutor
from user_manager import UserManager
import datetime as dt

users = UserManager()
users.add_user("alice", quota=5)

scheduler = Scheduler(
    TaskExecutor(users),
    clock=lambda: dt.datetime(2024, 1, 1, 12, 0),
)
scheduler.add_tasks([
    Task(user="alice", time="12:00", action="sync",   target="/a", id="t1"),
    Task(user="alice", time="12:00", action="backup", target="/b", id="t2"),
    Task(user="alice", time="12:00", action="delete", target="/c", id="t3"),
])

results = scheduler.run_once()
assert all(r.status.value == "executed" for r in results)
assert users.get("alice").executed == 3
```

### Configurable task parameters

`params` is forwarded verbatim to the handler as `Mapping[str, Any]`:

```python
Task(
    user="bob",
    time="03:00",
    action="backup",
    target="/srv/db",
    params={"compress": True, "level": 9, "retention_days": 30},
)
```

Whatever the handler reads from `params` is entirely up to the handler.

### Deterministic clock

```python
import datetime as dt
fixed = lambda: dt.datetime(2024, 6, 1, 9, 30)
scheduler = Scheduler(TaskExecutor(users), clock=fixed)
```

---

## Execution Flow

For each task whose `time == now`:

```
Scheduler.run_once()
  └─► TaskExecutor.execute(task)
        ├─ UserManager.get(task.user)
        │     ├─ UnknownUserError  →  Status.UNKNOWN_USER   (warning)
        │     └─ ok
        ├─ UserManager.has_capacity(task.user)
        │     ├─ False             →  Status.QUOTA_EXCEEDED (info)
        │     └─ True
        ├─ self._handlers.get(task.action)
        │     ├─ None              →  Status.UNKNOWN_ACTION (error)
        │     └─ handler
        ├─ handler(task.target, task.params)
        │     ├─ raises            →  Status.FAILED         (exception log)
        │     └─ returns detail
        ├─ UserManager.consume(task.user)   ← executed += 1
        └─ Status.EXECUTED                  (info)
```

---

## Status Codes

| Status | Meaning | Counter consumed? |
|---|---|---|
| `EXECUTED` | Handler ran and returned | ✅ yes |
| `QUOTA_EXCEEDED` | User hit their `quota` | ❌ no |
| `UNKNOWN_USER` | `task.user` not registered | ❌ no |
| `UNKNOWN_ACTION` | `task.action` not registered | ❌ no |
| `FAILED` | Handler raised an exception | ❌ no |

---

## Logging

Every module declares `logger = logging.getLogger(__name__)`:

| Logger | Levels used |
|---|---|
| `scheduler` | `INFO` on each tick, `DEBUG` on task registration |
| `executor` | `DEBUG` on registration, `INFO` on success / quota, `WARNING` on unknown user, `ERROR` on unknown action, `EXCEPTION` on handler failure |
| `user_manager` | `DEBUG` on register / consume, `WARNING` on overwrite |
| `__main__` | `INFO` for summary and per-result lines |

Configure the level via `configure_logging(logging.DEBUG)` in `main.py`
(or `logging.basicConfig` in your own entry point).

---

## Testing

Install pytest and run from `pyton-test/`:

```bash
pip install pytest
python -m pytest test_scheduler.py -v
```

The suite covers:

- Task validation (bad time format)
- `Task.from_dict` round-trip
- Single execution
- Multiple tasks per user + quota enforcement
- Configurable params reaching the handler
- Unknown user / unknown action (no crash)
- Handler exception containment (counter **not** consumed)
- Wrong-minute skipping
- `UnknownUserError` on direct lookup

All tests use an injected clock (`_clock(hour, minute)`), so they never
depend on wall time.

---

## Design Notes

**Why injectable clock?** Determinism. Tests and demos set a fixed time;
production uses `datetime.now`.

**Why frozen `Task`?** Tasks are data, not state machines. Freezing
prevents accidental mutation during iteration and makes them hashable.

**Why a flat task list?** The requirement "one user, multiple tasks" is
trivially satisfied — no per-user container needed. Filtering by time is
O(n) which is fine for a simple scheduler.

**Why a strategy registry instead of `if action == "sync": ...`?**
Open/Closed. New actions are registered without editing the executor.

**Why check quota *before* action lookup?** Preserves the original
script's precedence: if a user is over quota, they see the quota message
even if they also specified an unknown action. This was intentional.

**Why doesn't `FAILED` consume quota?** A failed handler didn't do work —
counting it against the user would be surprising. If your semantics
differ, call `users.consume()` in an `except` branch instead.

**Thread safety.** None. The scheduler is single-writer. If you add
concurrency, wrap `UserManager` mutations in a `threading.Lock`, or run
the scheduler under one dedicated thread.

---

## Extending the System

### Add a new action (callable)

```python
executor.register_action("rotate", lambda target, params: do_rotate(target, params) or "ok")
```

### Add a new action (OOP)

```python
class RotateStrategy(BaseStrategy):
    name = "rotate"
    def perform(self, target, params):
        # ... do work ...
        return f"rotate:{target}"

executor.register_action("rotate", RotateStrategy())
```

### Load tasks from JSON/YAML

```python
import json
from task import Task

with open("tasks.json") as f:
    raw = json.load(f)

scheduler.add_tasks(Task.from_dict(item) for item in raw)
```

### Replace the stdout "execution" with real work

Override the default strategy:

```python
from executor import BaseStrategy

class SyncToDisk(BaseStrategy):
    name = "sync"
    def perform(self, target, params):
        mode = params.get("mode", "incremental")
        # real filesystem sync here...
        return f"sync:{target}:{mode}"

executor.register_action("sync", SyncToDisk())
```

Registering an action **replaces** any previous handler for that name.

---

## Behaviour Parity with Original Script

The refactor preserves the original behaviour on the sample scenario:

| Original | Refactored |
|---|---|
| Iterate `tasks`, filter by `strftime("%H:%M")` | `Scheduler.run_once` filters identically |
| `if users[user]['executed'] >= quota: print(f"{user} has exceeded quota.")` | `Status.QUOTA_EXCEEDED` + same message via `logging` |
| `print(f"Executing {action} on {target} for {user}")` | `print("Executing {action} on {target} params=...")`; user is in the `INFO` log line |
| `users[user]['executed'] += 1` on success | `UserManager.consume()` after handler returns |

**One intentional cosmetic difference:** the original embedded `for {user}`
inside the printed line; the refactor prints `params=...` instead and
logs `for {user}` via `logging`. If **byte-for-byte stdout parity** is a
hard requirement, modify `BaseStrategy.__call__` (or the specific
strategies) to accept and print the user — but that couples strategies to
the user concept, which is why it was left out.
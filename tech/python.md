# Python

## What it is

**Python** is a programming language: you write instructions in a text file (a `.py` file), and a program called the **interpreter** reads the file and carries the instructions out one after another. It is known for being readable, and it comes with a large **standard library** of ready-made tools (files, text, dates, networking). Python is **dynamically typed** (a name can hold any kind of value, checked when the line runs), but it supports optional **type hints** that other tools check beforehand (see the typing note).

## Why this repository uses it

The load script, the lock experiments, the safe migration steps, the plan-flip experiment and the replay that chains them are Python, and so are the tests. The code is arranged in four layers; this note walks through `domain`, `application` and the shared start-up code of `interfaces`. The other modules are explained where their main technology is: `load_runner.py`, `lock_experiments.py` and the thread use of `schema_changes.py` in the threads note; `postgres.py`, `lab_table.py`, `schema_changes.py`, `plan_flip.py` and `health_probes.py` in the psycopg and PostgreSQL notes; `settings.py` in the environment-variables note; `logging.py` in the logging note; `shutdown.py` and the `*_cli.py` files in the command-line note; `artifacts.py`, `retry.py` and `sql_script.py` in the standard-library note.

## Where it appears

| Folder | What is there |
|---|---|
| `src/locks_lab/domain/` | Pure rules and values: window statistics and the 2x bar, the lock queue as values, backfill id ranges, plan-flip parsing, outcomes, lesson names, host load, errors. No input or output. |
| `src/locks_lab/application/` | The experiments (`Scenarios`), the replay, the report, the health use case, and the ports they need. |
| `src/locks_lab/infrastructure/` | The code that touches the outside world: PostgreSQL, threads, files. |
| `src/locks_lab/interfaces/` | The three commands and the composition root. |
| `tests/` | Unit, integration and end-to-end tests (pytest note). |

## How it works underneath

**Running.** `python file.py` starts the interpreter as a process, which compiles the file into **bytecode** (a compact internal form), then runs it. `python -m package.module` runs a module found through the import system; the code under `if __name__ == "__main__":` runs only when the file is started this way, not when it is imported.

**Names and values.** `x = 5` makes the name `x` refer to the value 5. Values have types: `int` (whole numbers), `float` (numbers with a fraction), `str` (text), `bool` (`True` or `False`), `None` (no value), `list` (`[1, 2]`, changeable), `tuple` (`(1, 2)`, fixed), `dict` (`{"a": 1}`, name-to-value map), `set` (`{1, 2}`, unique items).

**Blocks are indented.** After a line ending in `:` (`if`, `for`, `def`, `class`, `try`, `with`), the following lines indented four spaces are its body.

**Statements you will meet.**

- `import module` and `from module import name` load code from another file. A leading dot (`from .plan import X`, `from ..domain import Y`) is a **relative import**: `.` means this package, `..` the parent package.
- `def name(parameters) -> result:` defines a **function**. `*` in the parameter list means "everything after this must be passed by name" (keyword-only). A default value (`attempts: int = 5`) makes an argument optional. `return value` ends the function with a result.
- `class Name:` defines a **class**: a recipe for objects bundling data and functions (**methods**). `self` is the object a method works on. `__init__` runs when an object is created. A class in parentheses (`class LabError(Exception)`) **inherits** from another class. A leading underscore (`_name`) marks something as private by convention.
- `@decorator` above a function or class passes it through another function that wraps or changes it. `@property` turns a method into something read like an attribute (`obj.speedup`); `@classmethod` makes a method that works on the class, not an object.
- `if` / `elif` / `else`, `for item in things:`, `while`, `break`, `continue`.
- `try:` / `except ErrorType as error:` / `finally:` handle errors. `raise Error("text")` creates one. `raise X from y` records that `y` was the cause. `finally` always runs.
- `with something as name:` runs a block with a **context manager** that sets up and always cleans up (a file closed, a connection closed).
- `assert condition, "message"` raises `AssertionError` if the condition is false.
- `yield` makes a function a **generator**: it produces values one at a time when asked. `yield from other` hands over the values of another generator.
- `lambda x: expression` is a one-line anonymous function.

**Expressions.** F-strings, `f"{value:.3f}"`, put values into text; after the colon comes a **format**: `.3f` is three digits after the point, `,` adds thousands separators, `8.1f` means width 8 with one decimal. A **comprehension** builds a collection in one line: `[x * 2 for x in items if x > 0]` (list), `{k: v for ...}` (dict), `(x for x in ...)` (generator). `a if condition else b` picks one. `*` before a collection inside brackets spreads its items: `[*first, *second]`. Slicing `items[1:5]` takes a range; `text[:60]` the first 60 characters.

**Truthiness.** `if items:` is true when the list is not empty; empty text, `0` and `None` are false.

**Errors.** An uncaught error ends the program with a **traceback**, a list of the lines that led to it, and exit code 1.

**Modules and packages.** One `.py` file is a module; a folder with `__init__.py` is a package. `__name__` is the module's name, or `"__main__"` when it was started directly. `__file__` is its path.

## Walkthrough of this repository's use

### `domain/errors.py`

`src/locks_lab/domain/errors.py`, lines 1 to 21:

```python
"""Named errors of the lab. Each says what went wrong in terms a reader of the lock views would use."""


class LabError(Exception):
    """Base class of every error this package raises on purpose."""


class PlanParseError(LabError):
    """A query plan did not have the lines or fields the lesson reads."""


class LockWaitTimeoutError(LabError):
    """A statement gave up waiting for a lock (lock_timeout), instead of joining the lock queue for good."""


class UnknownMigrationError(LabError):
    """A migration number the lesson does not have."""


class LessonInterruptedError(LabError):
    """The replay was asked to stop (SIGINT or SIGTERM) between two steps."""
```

Line 1 is a **docstring**: a text in triple quotes as the first statement of a module, class or function; tools show it as documentation. `class LabError(Exception):` defines a new kind of error that **inherits** from Python's built-in `Exception`; the body is only a docstring, which is a complete class. The other four classes inherit from `LabError`, so one `except LabError` catches every error this package raises on purpose, and a specific `except LockWaitTimeoutError` catches one kind. Each name ends in `Error` (ruff rule `N818`) and each docstring says what happened in terms of the lock views.

### `domain/host.py`

`src/locks_lab/domain/host.py`, lines 1 to 27:

```python
"""How busy the machine was while something was measured, so a reader can discount the milliseconds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HostLoad:
    """The 1-minute load average and the CPU count at the start of a measurement."""

    load_average: float
    cpus: int

    @property
    def loaded(self) -> bool:
        """True when more than half a runnable task per CPU was waiting: timings are inflated."""
        return self.load_average > self.cpus / 2

    def note(self) -> str:
        """One sentence for the results file."""
        if self.loaded:
            return (
                f"Measured on a loaded machine (load average {self.load_average:.1f} on {self.cpus} CPUs); rerun "
                "`make run` on a quiet machine for clean figures. The ratios survive load better than the milliseconds."
            )
        return f"Measured at load average {self.load_average:.1f} on {self.cpus} CPUs."
```

- Line 3 `from __future__ import annotations` makes type hints be stored as text and evaluated lazily (typing note).
- Line 5 imports `dataclass`; lines 8 to 13 define a class with two fields; the dataclass note explains what the decorator generates.
- `@property def loaded(self) -> bool:` is read as `host_load.loaded`, without parentheses. It compares the load average with half the number of CPUs; `>` gives a `bool`.
- `note` returns text. `if self.loaded:` chooses the branch. Inside the `return (...)`, two string literals side by side are joined into one by Python. The first is an **f-string** (prefix `f`): `{self.load_average:.1f}` inserts the number with one decimal, `{self.cpus}` inserts the CPU count. The backticks inside the text are just characters (they make Markdown show code).
- The second `return` is the quiet-machine case.


### `domain/lesson.py`

`src/locks_lab/domain/lesson.py`, lines 1 to 12:

```python
"""The lesson's names: the objects its migrations create and the plans the plan-flip experiment captures."""

COLUMN = "flagged"
CHECK_CONSTRAINT = "flagged_not_null"
DEVICE_INDEX = "idx_events_device_created"
EXTENDED_STATISTICS = "events_region_city"
FLIP_PLANS = ("f1_stale_statistics", "f2_after_analyze", "f3_after_extended_statistics")
FLIP_PLAN_LABELS = {
    "f1_stale_statistics": "Before statistics catch up",
    "f2_after_analyze": "After ANALYZE",
    "f3_after_extended_statistics": "After extended statistics",
}
```

Module-level constants (capital letters by convention): the names of the objects the migrations create (`COLUMN = "flagged"`, `CHECK_CONSTRAINT`, `DEVICE_INDEX`, `EXTENDED_STATISTICS`) and `FLIP_PLANS`, a tuple of the three plan names. `FLIP_PLAN_LABELS` is a **dictionary** (`{key: value, ...}`) from each plan name to the label shown in the results table. Keeping the names in one place means a typo cannot make the Python and the SQL disagree silently.

### `domain/backfill.py`

`src/locks_lab/domain/backfill.py`, lines 1 to 15:

```python
"""The shape of a batched backfill: id ranges of a fixed size, so no single transaction touches the whole table."""

from __future__ import annotations

from collections.abc import Iterator


def id_ranges(first_id: int, last_id: int, batch_size: int) -> Iterator[tuple[int, int]]:
    """Inclusive (first, last) id ranges of `batch_size` ids from `first_id` up to and including `last_id`."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    start = first_id
    while start <= last_id:
        yield start, min(start + batch_size - 1, last_id)
        start += batch_size
```

`id_ranges(first_id, last_id, batch_size)` is a **generator** (it contains `yield`): it produces one `(first, last)` pair at a time instead of building a list of two million ids. `-> Iterator[tuple[int, int]]` says what it yields. `if batch_size < 1: raise ValueError(...)` refuses a nonsense argument. The `while start <= last_id:` loop yields `start, min(start + batch_size - 1, last_id)` (the range is inclusive on both ends; `min` shortens the last range) and then `start += batch_size`. For `id_ranges(1, 5, 2)` it yields `(1, 2)`, `(3, 4)`, `(5, 5)`. A caller uses it in a `for` loop, and the batches are made as needed.

### `domain/stats.py`

`src/locks_lab/domain/stats.py`, lines 1 to 56:

```python
"""What the load script measures and how a window of it is summarized.

A second's p99 counts the operations that finished in it and the age of any operation still waiting, so a stall
shows up as a high p99 even when nothing completes (otherwise a full outage would look like silence).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

STALL_MS = 500  # an operation older than this at a one-second tick makes that second a stalled one


def percentile(values: Sequence[float], fraction: float) -> float:
    """The nearest-rank percentile (`fraction` in 0..1); 0.0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


@dataclass(frozen=True, slots=True)
class Sample:
    """One finished statement of the load."""

    finished_at: float
    operation: str
    milliseconds: float
    ok: bool


@dataclass(frozen=True, slots=True)
class Tick:
    """One second of the load as the reporter saw it."""

    t: float
    ops: int
    errors: int
    p99_ms: float
    oldest_inflight_ms: float


def make_tick(now: float, window_start: float, samples: Sequence[Sample], inflight_ages_ms: Sequence[float]) -> Tick:
    """The tick for the window [window_start, now): finished samples plus the ages of operations still waiting."""
    finished = [sample for sample in samples if window_start <= sample.finished_at < now]
    latencies = [sample.milliseconds for sample in finished] + list(inflight_ages_ms)
    return Tick(
        t=now,
        ops=len(finished),
        errors=sum(not sample.ok for sample in finished),
        p99_ms=percentile(latencies, 0.99),
        oldest_inflight_ms=max(inflight_ages_ms, default=0.0),
    )

```

- `import math` and `from collections.abc import Sequence`; `STALL_MS = 500` is a constant, with a comment saying what it means.
- `percentile(values, fraction)`: the **nearest-rank percentile**. An empty input gives `0.0`. Otherwise `ordered = sorted(values)` sorts a copy, and `ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]` picks the element at rank `ceil(fraction × n)` (rank 1 is index 0, hence the `- 1`; `max(0, ...)` keeps the index from going negative). For 100 values and `fraction=0.99`, `ceil(99.0) - 1 = 98`: the 99th smallest. So "p99" is the latency that 99 percent of operations stayed below.
- `Sample` is one finished statement: when it finished, which operation, its duration in milliseconds, whether it succeeded. `Tick` is one second of the load as the reporter saw it.
- `make_tick(now, window_start, samples, inflight_ages_ms)`: list comprehensions pick the samples that finished in the window (`window_start <= sample.finished_at < now` is a **chained comparison**) and build `latencies` from their durations **plus the ages of operations still waiting** (`+ list(inflight_ages_ms)` concatenates two lists). That is the docstring's key idea: a stall shows as a high p99 even if nothing finishes. `sum(not sample.ok for sample in finished)` counts failures: `not sample.ok` is `True` (1) for a failure, and `sum` adds the `True`s. `max(inflight_ages_ms, default=0.0)` is the oldest waiting operation, or 0.0 when there is none (`default=` avoids an error on an empty sequence).

`src/locks_lab/domain/stats.py`, lines 58 to 114:

```python
@dataclass(frozen=True, slots=True)
class WindowSummary:
    """A stretch of the load: rate, errors, latency and stalls."""

    seconds: float
    ops: int
    ops_per_second: float
    errors: int
    p50_ms: float
    p99_ms: float
    max_ms: float
    worst_second_p99_ms: float
    stalled_seconds: int


def summarize(samples: Sequence[Sample], ticks: Sequence[Tick], start: float, end: float) -> WindowSummary:
    """Summarize what finished in [start, end); a tick counts when its midpoint lies inside the window."""
    window = [sample for sample in samples if start <= sample.finished_at < end]
    inside = [tick for tick in ticks if start <= tick.t - 0.5 < end]
    latencies = [sample.milliseconds for sample in window]
    seconds = max(end - start, 1e-9)
    return WindowSummary(
        seconds=round(seconds, 1),
        ops=len(window),
        ops_per_second=round(len(window) / seconds, 1),
        errors=sum(not sample.ok for sample in window),
        p50_ms=round(percentile(latencies, 0.50), 2),
        p99_ms=round(percentile(latencies, 0.99), 2),
        max_ms=round(max(latencies, default=0.0), 1),
        worst_second_p99_ms=max((tick.p99_ms for tick in inside), default=0.0),
        stalled_seconds=sum(tick.oldest_inflight_ms >= STALL_MS for tick in inside),
    )


@dataclass(frozen=True, slots=True)
class Bar:
    """The lesson's bar for a change that must not hurt.

    p99 at most `factor` times the baseline, no errors, no stalled second.
    """

    baseline_p99_ms: float
    factor: float = 2.0

    @classmethod
    def bracketing(cls, opening: WindowSummary, closing: WindowSummary, factor: float = 2.0) -> Bar:
        """The bar from the higher of two baselines taken before and after, because other work on the machine moves
        p99 as much as a migration does."""
        return cls(max(opening.p99_ms, closing.p99_ms), factor)

    @property
    def limit_ms(self) -> float:
        return self.baseline_p99_ms * self.factor

    def allows(self, window: WindowSummary) -> bool:
        """True when the window stayed within the bar."""
        return window.p99_ms <= self.limit_ms and window.errors == 0 and window.stalled_seconds == 0
```

- `WindowSummary` holds the numbers of a stretch of the load.
- `summarize(samples, ticks, start, end)`: `window` are the samples finished in `[start, end)`; `inside` are the ticks whose midpoint (`tick.t - 0.5`) lies inside. `seconds = max(end - start, 1e-9)` avoids division by zero (`1e-9` is 0.000000001). `round(x, 2)` rounds to 2 decimals. `stalled_seconds=sum(tick.oldest_inflight_ms >= STALL_MS for tick in inside)` counts the ticks in which some operation had waited 500 ms or more.
- `Bar` is the lesson's pass mark: p99 at most `factor` (2.0) times the baseline, no errors, no stalled second. The **class method** `bracketing(cls, opening, closing, factor=2.0)` builds it from the higher of two baselines, taken before and after the change (the docstring explains why: other work on the machine moves p99 as much as a migration does). `limit_ms` is a property (`baseline × factor`), and `allows(window)` returns the combined test with `and`: `window.p99_ms <= self.limit_ms and window.errors == 0 and window.stalled_seconds == 0`.

### `domain/locks.py`

`src/locks_lab/domain/locks.py`, lines 1 to 69:

```python
"""What the lock views show, as values: who waits for whom, which requests are queued, which lock a step held."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WaitingSession:
    """A session waiting on a lock (pg_stat_activity), and the sessions it is blocked by."""

    pid: int
    application: str
    blocked_by: tuple[int, ...]
    waiting_seconds: float
    query: str


@dataclass(frozen=True, slots=True)
class LockRequest:
    """One lock on the table, granted or still queued (pg_locks)."""

    pid: int
    application: str
    mode: str
    granted: bool


@dataclass(frozen=True, slots=True)
class LockSnapshot:
    """The lock queue at one moment."""

    waiting: tuple[WaitingSession, ...]
    queue: tuple[LockRequest, ...]

    def waiting_application(self, application: str) -> tuple[WaitingSession, ...]:
        """The waiting sessions that belong to the named application."""
        return tuple(session for session in self.waiting if session.application == application)

    def request_of(self, pid: int) -> LockRequest | None:
        """The table lock the session holds or waits for."""
        return next((request for request in self.queue if request.pid == pid), None)

    def format(self) -> str:
        """The two views as text, the way the lesson's notes show them."""
        lines = [
            "pg_stat_activity, sessions waiting on a lock (oldest first):",
            f"{'pid':>7} {'application':18} {'blocked by':14} {'waiting s':>9}  query",
        ]
        lines += [
            f"{s.pid:>7} {s.application:18} {list(s.blocked_by)!s:14} {s.waiting_seconds:>9}  {s.query}"
            for s in self.waiting
        ]
        lines += [
            "",
            "pg_locks on events (granted first, then the queue):",
            f"{'pid':>7} {'application':18} {'mode':24} granted",
        ]
        lines += [f"{r.pid:>7} {r.application:18} {r.mode:24} {r.granted}" for r in self.queue]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class LockReport:
    """A statement run in its own transaction: how long it took, the lock modes it held, and the tries it needed."""

    seconds: float
    lock_modes: tuple[str, ...]
    attempts: int = 1
```

Four dataclasses describe what the lock views show: `WaitingSession` (a session waiting on a lock, and who blocks it), `LockRequest` (one lock on the table, granted or queued), `LockSnapshot` (the whole queue at one moment) and `LockReport` (a statement's duration and the lock modes it held; `attempts: int = 1` has a default). `LockSnapshot.waiting_application(name)` returns a tuple of the waiting sessions of one application (a generator expression inside `tuple(...)`). `request_of(pid)` uses `next((request for request in self.queue if request.pid == pid), None)`: `next(iterator, default)` returns the first match or `None`. `format()` builds text lines with f-strings and alignment formats: `{'pid':>7}` right-aligns in 7 columns, `{'application':18}` pads to 18, `{list(s.blocked_by)!s:14}` converts the tuple to a list and then to text (`!s`) and pads to 14. The result is what ends up in `sql/explain/lock_queue.txt`.

### `domain/flip.py`

`src/locks_lab/domain/flip.py`, lines 1 to 39:

```python
"""What the plan-flip experiment reads from a plan: the planner's estimate, the node types, the time."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .errors import PlanParseError

_NODE = re.compile(r"^\s*(?:->\s*)?(Seq Scan|Index Scan Backward|Index Scan|Bitmap Heap Scan|Sort)\b", re.MULTILINE)
_ESTIMATE = re.compile(r"\(cost=[^)]*rows=(\d+)")
_EXECUTION = re.compile(r"Execution Time: ([\d.]+) ms")


@dataclass(frozen=True, slots=True)
class FlipPlan:
    """The estimate on the deepest node, the node types in plan order, and the execution time."""

    estimate: int
    nodes: tuple[str, ...]
    milliseconds: float

    @property
    def scans_everything(self) -> bool:
        return "Seq Scan" in self.nodes

    @property
    def walks_the_index(self) -> bool:
        return "Index Scan Backward" in self.nodes


def parse_flip_plan(lines: Sequence[str]) -> FlipPlan:
    """Read a plan from `EXPLAIN (ANALYZE, BUFFERS)` text."""
    text = "\n".join(lines)
    estimates, execution = _ESTIMATE.findall(text), _EXECUTION.search(text)
    if not estimates or execution is None:
        raise PlanParseError("the plan has no row estimate or no Execution Time: was it produced with ANALYZE?")
    return FlipPlan(int(estimates[-1]), tuple(dict.fromkeys(_NODE.findall(text))), float(execution.group(1)))
```

(The regular-expressions note explains the patterns.) `FlipPlan` has the planner's estimate, the node types and the time, with two properties that answer yes/no questions: `scans_everything` (is there a `Seq Scan`?) and `walks_the_index` (is there an `Index Scan Backward`?). `parse_flip_plan(lines)` joins the lines, finds all `rows=` estimates with `findall` (`estimates[-1]` is the **last** one, the estimate on the deepest node, since the plan prints outer nodes first), the execution time with `search`, raises `PlanParseError` if either is missing, and returns a `FlipPlan` whose node tuple is made unique and ordered by `dict.fromkeys(...)`.

### `domain/outcomes.py`

`src/locks_lab/domain/outcomes.py`, lines 1 to 56:

```python
"""What the experiments hand back, as plain values."""

from __future__ import annotations

from dataclasses import dataclass

from .locks import LockSnapshot


@dataclass(frozen=True, slots=True)
class TableSize:
    """The events table's size and the dead row versions an update-heavy change leaves behind."""

    pretty: str
    dead_rows: int


@dataclass(frozen=True, slots=True)
class ConflictOutcome:
    """The safe ALTER met a long read: did it give up at lock_timeout, and how long did it wait?"""

    failed_fast: bool
    seconds: float


@dataclass(frozen=True, slots=True)
class QueueOutcome:
    """The naive ALTER behind a long read: the lock views mid-pile-up, and how long the ALTER waited."""

    snapshot: LockSnapshot
    alter_seconds: float


@dataclass(frozen=True, slots=True)
class InterruptedBuild:
    """A CREATE INDEX CONCURRENTLY cancelled on purpose: what it left behind."""

    cancelled: bool
    invalid_indexes: tuple[str, ...]
    ready_but_invalid: bool


@dataclass(frozen=True, slots=True)
class RebuiltIndex:
    """The invalid index dropped and the build run again."""

    seconds: float
    valid: bool


@dataclass(frozen=True, slots=True)
class FlipOutcome:
    """The correlated month: how many rows match, and the three captured plans' lines by name."""

    actual_rows: int
    plans: dict[str, tuple[str, ...]]
```

Six frozen dataclasses for what the experiments hand back: `TableSize`, `ConflictOutcome`, `QueueOutcome`, `InterruptedBuild`, `RebuiltIndex` and `FlipOutcome` (which holds `plans: dict[str, tuple[str, ...]]`, a dictionary from plan name to its lines). They are plain values with no behaviour, which makes the use cases easy to test.

### `application/scenarios.py`

`src/locks_lab/application/scenarios.py`, lines 1 to 105:

```python
"""Use cases: each experiment of the lesson, measured against the running load.

Every method takes the load as a parameter where it needs to look at it, and returns a plain result. The replay
chains them with long windows; the tests call them with short ones.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..domain.flip import FlipPlan, parse_flip_plan
from ..domain.locks import LockReport, LockSnapshot
from ..domain.outcomes import ConflictOutcome, InterruptedBuild, TableSize
from ..domain.stats import WindowSummary
from .ports import LabTable, LoadGenerator, LockExperiments, PlanFlipLab, SchemaChanges

SETTLE_SECONDS = 2.0  # let operations that were blocked finish before a window is summarized


@dataclass(frozen=True, slots=True)
class LockQueueResult:
    """The pile-up behind a naive ALTER."""

    snapshot: LockSnapshot
    during: WindowSummary
    after: WindowSummary
    alter_seconds: float
    hold_seconds: float


@dataclass(frozen=True, slots=True)
class SafeMigrationResult:
    """The column added with a lock_timeout and backfilled in batches."""

    summary: WindowSummary
    seconds: float
    batches: int
    add_column_attempts: int
    rows_still_null: int


@dataclass(frozen=True, slots=True)
class PlainIndexResult:
    """The naive index build and what the load felt."""

    build_seconds: float
    summary: WindowSummary


@dataclass(frozen=True, slots=True)
class ConcurrentIndexResult:
    """The interrupted concurrent build, its cleanup and the rebuild under load."""

    interrupted: InterruptedBuild
    build_seconds: float
    summary: WindowSummary
    valid_after_rebuild: bool


@dataclass(frozen=True, slots=True)
class NaiveNotNullResult:
    """SET NOT NULL with no validated CHECK."""

    report: LockReport
    summary: WindowSummary


@dataclass(frozen=True, slots=True)
class SafeNotNullResult:
    """NOT NULL in three moves."""

    steps: dict[str, LockReport]
    summary: WindowSummary


@dataclass(frozen=True, slots=True)
class FlipResult:
    """The plan regression: the row count and the three plans, parsed."""

    actual_rows: int
    plans: dict[str, FlipPlan]
    lines: dict[str, tuple[str, ...]]


class Scenarios:
    """The lesson's experiments over the ports."""

    def __init__(
        self,
        *,
        table: LabTable,
        locks: LockExperiments,
        changes: SchemaChanges,
        flip: PlanFlipLab,
        pause: Callable[[float], None],
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self._table = table
        self._locks = locks
        self._changes = changes
        self._flip = flip
        self._pause = pause
        self._should_stop = should_stop

```

- Seven result dataclasses (`LockQueueResult`, `SafeMigrationResult`, ...).
- `class Scenarios` receives its collaborators by keyword (`*` in the parameter list): the four ports (`table`, `locks`, `changes`, `flip`), `pause: Callable[[float], None]` (a function that waits, `time.sleep` in production, a recorder in tests) and `should_stop`. It stores them with a leading underscore.
- `lock_queue(load, hold_seconds=6.0)`: remembers the time (`start = load.now()`), runs the experiment through the port, summarizes what the load felt while it ran (`load.summary(start, load.now())`) and for 3 more seconds after (`load.measure(3)`), and returns a `LockQueueResult`.
- `forced_conflict(lock_timeout="1s")`: runs the experiment, then `self._pause(SETTLE_SECONDS)` (2 seconds, a module constant) so operations queued behind the failed ALTER can finish before anything else is measured.

`src/locks_lab/application/scenarios.py`, lines 106 to 173:

```python
    def lock_queue(self, load: LoadGenerator, hold_seconds: float = 6.0) -> LockQueueResult:
        """Step 2: a long read, then a naive ALTER behind it."""
        start = load.now()
        outcome = self._locks.lock_queue(hold_seconds)
        during = load.summary(start, load.now())
        after = load.measure(3)
        return LockQueueResult(outcome.snapshot, during, after, outcome.alter_seconds, hold_seconds)

    def forced_conflict(self, lock_timeout: str = "1s") -> ConflictOutcome:
        """Step 3: the safe ALTER must give up at its lock_timeout, then the queue it joined drains."""
        outcome = self._locks.forced_conflict(lock_timeout)
        self._pause(SETTLE_SECONDS)  # operations queued behind the failed ALTER finish first
        return outcome

    def safe_migration(self, load: LoadGenerator, batch_size: int, pause_seconds: float) -> SafeMigrationResult:
        """Step 3: add the column with a lock_timeout, backfill in batches, and summarize the load meanwhile."""
        start = load.now()
        attempts = self._changes.add_flagged_column()
        batches = self._changes.backfill_flagged(batch_size, pause_seconds, self._should_stop)
        end = load.now()
        return SafeMigrationResult(
            summary=load.summary(start, end),
            seconds=end - start,
            batches=batches,
            add_column_attempts=attempts,
            rows_still_null=self._changes.unflagged_rows(),
        )

    def plain_index(self, load: LoadGenerator) -> PlainIndexResult:
        """Step 4, the naive way: writes wait for the whole build."""
        start = load.now()
        build_seconds = self._changes.plain_index_build()
        self._pause(SETTLE_SECONDS)
        return PlainIndexResult(build_seconds, load.summary(start, load.now()))

    def concurrent_index(self, load: LoadGenerator) -> ConcurrentIndexResult:
        """Step 4: interrupt a concurrent build on purpose, find the invalid index, drop it, rebuild under load."""
        interrupted = self._changes.interrupted_concurrent_build()
        start = load.now()
        rebuilt = self._changes.rebuild_invalid_index()
        self._pause(SETTLE_SECONDS)
        return ConcurrentIndexResult(interrupted, rebuilt.seconds, load.summary(start, load.now()), rebuilt.valid)

    def naive_not_null(self, load: LoadGenerator) -> NaiveNotNullResult:
        """Step 5, the naive way: a scan under ACCESS EXCLUSIVE."""
        start = load.now()
        report = self._changes.naive_set_not_null()
        self._pause(SETTLE_SECONDS)
        return NaiveNotNullResult(report, load.summary(start, load.now()))

    def safe_not_null(self, load: LoadGenerator) -> SafeNotNullResult:
        """Step 5: NOT VALID, VALIDATE, SET NOT NULL."""
        start = load.now()
        steps = self._changes.not_null_in_three_moves()
        self._pause(SETTLE_SECONDS)
        return SafeNotNullResult(steps, load.summary(start, load.now()))

    def plan_flip(self) -> FlipResult:
        """Step 6: stale statistics, then ANALYZE, then extended statistics."""
        outcome = self._flip.run()
        return FlipResult(
            outcome.actual_rows,
            {name: parse_flip_plan(lines) for name, lines in outcome.plans.items()},
            outcome.plans,
        )

    def table_size(self) -> TableSize:
        return self._table.size()
```

- `safe_migration`: records the start, adds the column, backfills in batches, records the end, and returns the summary of the load for that period, the elapsed seconds, the number of batches, the attempts the ALTER needed and the rows still NULL.
- `plain_index`, `concurrent_index`, `naive_not_null`, `safe_not_null`: each starts a stopwatch with the load, calls one adapter method, pauses 2 seconds to let blocked operations finish, and returns the load's summary for that window.
- `plan_flip`: calls the port, then `{name: parse_flip_plan(lines) for name, lines in outcome.plans.items()}` — a **dictionary comprehension** — turns each plan's lines into a `FlipPlan`.
- `table_size` returns `self._table.size()`.

### `application/replay.py`

`src/locks_lab/application/replay.py`, lines 1 to 62:

```python
"""Use case: replay the lesson with the load running throughout.

Baseline, the lock pile-up, the safe migration, the concurrent index, NOT NULL in three moves, the plan flip, and a
closing baseline that brackets the changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..domain.errors import LessonInterruptedError
from ..domain.host import HostLoad
from ..domain.outcomes import ConflictOutcome, TableSize
from ..domain.stats import Bar, WindowSummary
from .ports import ArtifactStore, LabTable, LoadGenerator
from .report import render_results
from .scenarios import (
    ConcurrentIndexResult,
    FlipResult,
    LockQueueResult,
    NaiveNotNullResult,
    PlainIndexResult,
    SafeMigrationResult,
    SafeNotNullResult,
    Scenarios,
)


@dataclass(frozen=True, slots=True)
class LessonResult:
    """Everything the replay measured."""

    rows: int
    baseline_seconds: int
    opening: WindowSummary
    closing: WindowSummary
    size_before: TableSize
    size_after_backfill: TableSize
    lock_queue: LockQueueResult
    conflict: ConflictOutcome
    safe: SafeMigrationResult
    plain_index: PlainIndexResult
    concurrent_index: ConcurrentIndexResult
    naive_not_null: NaiveNotNullResult
    safe_not_null: SafeNotNullResult
    flip: FlipResult
    batch_size: int
    pause_seconds: float
    host_load: HostLoad | None = None

    @property
    def bar(self) -> Bar:
        """Twice the higher of the opening and closing baselines."""
        return Bar.bracketing(self.opening, self.closing)


class ReplayLesson:
    """Runs the scenarios in the lesson's order against the running load and keeps the evidence.

    `should_stop` is polled between steps; when it returns true the replay raises `LessonInterruptedError` and leaves
    the table to be reset by the next run.
```

`LessonResult` has 17 fields (frozen dataclass) and a computed property `bar` that returns `Bar.bracketing(self.opening, self.closing)`: twice the higher of the opening and closing baselines. The docstring of `ReplayLesson` explains `should_stop`.

`src/locks_lab/application/replay.py`, lines 63 to 156:

```python
    """

    def __init__(
        self,
        *,
        load: LoadGenerator,
        table: LabTable,
        scenarios: Scenarios,
        store: ArtifactStore,
        baseline_seconds: int,
        closing_seconds: int = 20,
        batch_size: int,
        pause_seconds: float,
        host_load: HostLoad | None = None,
        progress: Callable[[str], None] = lambda _message: None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self._load = load
        self._table = table
        self._scenarios = scenarios
        self._store = store
        self._baseline_seconds = baseline_seconds
        self._closing_seconds = closing_seconds
        self._batch_size = batch_size
        self._pause_seconds = pause_seconds
        self._host_load = host_load
        self._progress = progress
        self._should_stop = should_stop

    def run(self) -> LessonResult:
        """Replay every step, write the notes, and return what was measured."""
        self._step("reset to the seed's rows")
        self._table.reset()
        rows = self._table.row_count()

        self._step(f"step 1: baseline, {self._baseline_seconds} s of steady load")
        opening = self._load.measure(self._baseline_seconds)
        size_before = self._table.size()

        self._step("step 2: a long read, then a naive ALTER behind it")
        queue = self._scenarios.lock_queue(self._load)
        self._store.save_text("lock_queue.txt", queue.snapshot.format())
        self._table.reset()

        self._step("step 3: the safe migration")
        conflict = self._scenarios.forced_conflict()
        self._table.reset()
        safe = self._scenarios.safe_migration(self._load, self._batch_size, self._pause_seconds)
        size_after = self._table.size()

        self._step("step 4: the index")
        plain = self._scenarios.plain_index(self._load)
        concurrent = self._scenarios.concurrent_index(self._load)

        self._step("step 5: NOT NULL")
        naive = self._scenarios.naive_not_null(self._load)
        three_moves = self._scenarios.safe_not_null(self._load)

        self._step("step 6: the plan flip")
        flip = self._scenarios.plan_flip()
        for name, lines in flip.lines.items():
            self._store.save_plan(name, lines)
        self._table.reset()

        self._step("closing baseline: the machine's own noise, to bracket the changes")
        closing = self._load.measure(self._closing_seconds)

        result = LessonResult(
            rows=rows,
            baseline_seconds=self._baseline_seconds,
            opening=opening,
            closing=closing,
            size_before=size_before,
            size_after_backfill=size_after,
            lock_queue=queue,
            conflict=conflict,
            safe=safe,
            plain_index=plain,
            concurrent_index=concurrent,
            naive_not_null=naive,
            safe_not_null=three_moves,
            flip=flip,
            batch_size=self._batch_size,
            pause_seconds=self._pause_seconds,
            host_load=self._host_load,
        )
        self._store.save_report(render_results(result))
        return result

    def _step(self, label: str) -> None:
        if self._should_stop():
            raise LessonInterruptedError("stopped between steps")
        self._progress(label)
        self._load.mark(label)
```

- `__init__` takes only keyword-only arguments; `closing_seconds: int = 20` has a default.
- `run()` is the lesson, in order: `_step(...)` announces and labels each stage; `self._table.reset()` puts the table back to the seed; `self._load.measure(self._baseline_seconds)` lets the load run alone; `self._scenarios.lock_queue(self._load)` and so on. `queue.snapshot.format()` is saved as `lock_queue.txt`; `for name, lines in flip.lines.items(): self._store.save_plan(name, lines)` saves the three plans. The final `closing` baseline brackets the changes. Then `LessonResult(...)` is built with keyword arguments and `render_results` makes the notes.
- `_step(label)` raises `LessonInterruptedError` if `should_stop()` is true, otherwise reports progress and writes the label into the load's per-second record (`self._load.mark(label)`), so a spike in `load-metrics.jsonl` can be matched to the step that caused it.

### `application/report.py`

`src/locks_lab/application/report.py`, lines 1 to 56:

```python
"""The results notes: a pure function from what was measured to Markdown."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain.lesson import FLIP_PLAN_LABELS
from ..domain.stats import Bar, WindowSummary

if TYPE_CHECKING:
    from .replay import LessonResult


def _row(label: str, window: WindowSummary, bar: Bar) -> str:
    verdict = "yes" if bar.allows(window) else "no"
    return (
        f"| {label} | {window.ops_per_second} | {window.errors} | {window.p99_ms} | {window.max_ms} | "
        f"{window.worst_second_p99_ms} | {window.stalled_seconds} | {verdict} |"
    )


def render_results(result: LessonResult) -> str:
    """Markdown with the windows table, the lock queue, each step's findings and the plan-flip table."""
    bar, queue, safe = result.bar, result.lock_queue, result.safe
    plain, concurrent = result.plain_index, result.concurrent_index
    naive, moves = result.naive_not_null, result.safe_not_null
    out = [
        "# Results of the last `make run` or `make measure`",
        "",
        f"Generated by `locks-lab-run` on {result.rows:,} rows with the load running throughout "
        f"({result.baseline_seconds} s baseline). The load is 40 iterations a second of insert, update and read "
        "(120 operations a second).",
        "",
        *([result.host_load.note(), ""] if result.host_load else []),
        "## What the load felt",
        "",
        "p99 is over the operations (single statements) that finished in the window. Worst second is the highest "
        "one-second p99, which also counts operations still waiting, so a stall shows even when nothing completes. "
        "A stalled second is one in which an operation had waited 500 ms or more. The last column is the strict "
        "test: p99 at most twice the baseline, no errors and no stalled second. The lesson asks for it only of the "
        "safe migration (step 3); for the others read max ms and stalled seconds.",
        "",
        "| Window | Ops/s | Errors | p99 ms | Max ms | Worst second p99 ms | Stalled seconds "
        "| Within 2x, no errors, no stall |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
        _row("1 baseline, opening", result.opening, bar),
        _row(f"1 baseline, closing ({result.closing.seconds:.0f} s)", result.closing, bar),
        _row(f"2 naive ALTER behind a long read ({queue.hold_seconds:.0f} s)", queue.during, bar),
        _row(f"3 safe migration: add column, full backfill ({safe.seconds:.0f} s)", safe.summary, bar),
        _row(f"4 plain CREATE INDEX ({plain.build_seconds:.1f} s build)", plain.summary, bar),
        _row(f"4 CREATE INDEX CONCURRENTLY ({concurrent.build_seconds:.1f} s build)", concurrent.summary, bar),
        _row(f"5 naive SET NOT NULL ({naive.report.seconds * 1000:.0f} ms)", naive.summary, bar),
        _row("5 NOT NULL in three moves", moves.summary, bar),
        "",
        f"Baseline p99 for the bar: {bar.baseline_p99_ms} ms (the higher of the opening and closing baselines). "
        f"After the pile-up, with the long read released: {queue.after.p99_ms} ms p99.",
```

- The `TYPE_CHECKING` import avoids a circular import (typing note).
- `_row(label, window, bar)` formats one table row; the verdict `"yes" if bar.allows(window) else "no"` is a conditional expression.
- `render_results(result)`: several assignments from one line, e.g. `bar, queue, safe = result.bar, result.lock_queue, result.safe` (tuple unpacking). The list `out` holds the Markdown lines; `*([result.host_load.note(), ""] if result.host_load else [])` spreads the machine-load note or nothing. F-strings use `{result.rows:,}` (thousands separators), `{result.closing.seconds:.0f}` (no decimals) and `{naive.report.seconds * 1000:.0f}` (seconds converted to milliseconds).

`src/locks_lab/application/report.py`, lines 57 to 119:

````python
        "",
        "## Step 2: the lock queue",
        "",
        f"The naive `ALTER TABLE events ADD COLUMN flagged boolean` waited {queue.alter_seconds:.1f} s for a read-only "
        "transaction and never held its lock until that ended. The snapshot taken mid-pile-up is in `lock_queue.txt`.",
        "",
        "```text",
        queue.snapshot.format().rstrip(),
        "```",
        "",
        "## Step 3: the safe migration",
        "",
        f"- Forced conflict: with a long read open, the safe `ALTER` (lock_timeout 1 s) failed after "
        f"{result.conflict.seconds:.2f} s (failed fast: {result.conflict.failed_fast}). It still held up the load for "
        "that second: a failed attempt queues too, so the timeout is also the longest stall a retry can cause.",
        f"- Add column: {safe.add_column_attempts} attempt(s). Backfill: {safe.batches} batches of "
        f"{result.batch_size:,} rows with a {result.pause_seconds} s pause, {safe.seconds:.0f} s in all; "
        f"rows still NULL afterwards: {safe.rows_still_null}.",
        f"- Bloat: table {result.size_before.pretty} before, {result.size_after_backfill.pretty} after the backfill "
        f"({result.size_after_backfill.dead_rows:,} dead row versions): every updated row is a new version.",
        "",
        "## Step 4: the index",
        "",
        f"- Plain `CREATE INDEX`: built in {plain.build_seconds:.1f} s; the load's slowest operation took "
        f"{plain.summary.max_ms} ms (baseline max is a few milliseconds), "
        "because inserts and updates waited for the build.",
        f"- `CREATE INDEX CONCURRENTLY` interrupted on purpose: cancelled = {concurrent.interrupted.cancelled}, "
        f"invalid indexes found = {list(concurrent.interrupted.invalid_indexes)}. Dropped, rebuilt in "
        f"{concurrent.build_seconds:.1f} s with {concurrent.summary.errors} load errors and a slowest operation of "
        f"{concurrent.summary.max_ms} ms; valid after rebuild: {concurrent.valid_after_rebuild}.",
        "",
        "## Step 5: NOT NULL in three moves",
        "",
        "| Move | Statement | Lock held | Time ms |",
        "|---|---|---|---:|",
    ]
    statements = {
        "add_check_not_valid": "ADD CONSTRAINT ... CHECK (flagged IS NOT NULL) NOT VALID",
        "validate": "VALIDATE CONSTRAINT",
        "set_not_null": "SET NOT NULL, then DROP CONSTRAINT",
    }
    for name, statement in statements.items():
        step = moves.steps[name]
        out.append(f"| {name} | `{statement}` | {', '.join(step.lock_modes)} | {step.seconds * 1000:.1f} |")
    out += [
        "",
        f"The naive `SET NOT NULL` on a scratch column held {', '.join(naive.report.lock_modes)} for "
        f"{naive.report.seconds * 1000:.0f} ms (a full scan), against a few milliseconds for the last move above.",
        "",
        "## Step 6: the plan flip",
        "",
        f"The new month holds {result.flip.actual_rows:,} rows with `region = 'pacific' AND city = 'seattle'`. "
        "Plans are in `f1_*.txt`, `f2_*.txt` and `f3_*.txt`.",
        "",
        "| Moment | Planner estimate | Actual rows | Plan | Execution ms |",
        "|---|---:|---:|---|---:|",
    ]
    for name, plan in result.flip.plans.items():
        out.append(
            f"| {FLIP_PLAN_LABELS[name]} | {plan.estimate:,} (filtered scan node) | {result.flip.actual_rows:,} | "
            f"{' / '.join(plan.nodes)} | {plan.milliseconds} |"
        )
    return "\n".join(out) + "\n"
````

The rest of the report: the lock-queue text in a fenced block (`queue.snapshot.format().rstrip()`), the findings of steps 3 and 4, a table for the three NOT NULL moves built in a `for name, statement in statements.items():` loop over a dictionary, and the plan-flip table in another loop, joining the node types with `' / '.join(plan.nodes)`.

### `application/health.py`

The health use case is the same module as in the other labs: `ProbeFailedError`, `ProbeResult`, `HealthReport` and `check_health(probes)` run each probe, record success or the failure message, and report healthy only when all are.

`src/locks_lab/application/health.py`, lines 1 to 43:

```python
"""Use case: ask every dependency whether it is usable."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .ports import HealthProbe


class ProbeFailedError(Exception):
    """A dependency is not usable; the message says why."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """The outcome of one health probe."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The outcomes of every probe; healthy only when all of them are."""

    results: tuple[ProbeResult, ...]

    @property
    def healthy(self) -> bool:
        return all(result.ok for result in self.results)


def check_health(probes: Iterable[HealthProbe]) -> HealthReport:
    """Run every probe and collect the outcomes; a failed probe is reported, not raised."""
    results = []
    for probe in probes:
        try:
            results.append(ProbeResult(probe.name, True, probe.check()))
        except ProbeFailedError as error:
            results.append(ProbeResult(probe.name, False, str(error)))
    return HealthReport(tuple(results))
```

`healthy` uses `all(...)`; `check_health` loops over probes, calls `probe.check()` inside `try`, and records either a good or a failed result; a failed probe is reported, not raised.

### `interfaces/common.py`

`src/locks_lab/interfaces/common.py`, lines 1 to 49:

```python
"""Startup shared by the programs: settings or a clear exit code 2, and the composition root."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from ..application.scenarios import Scenarios
from ..domain.host import HostLoad
from ..infrastructure.lab_table import PostgresLabTable
from ..infrastructure.lock_experiments import PostgresLockExperiments
from ..infrastructure.logging import configure_logging
from ..infrastructure.plan_flip import PostgresPlanFlip
from ..infrastructure.schema_changes import PostgresSchemaChanges
from ..infrastructure.settings import ConfigurationError, Settings


def load_settings() -> Settings | None:
    """Read and validate the environment, configure logging, or print the problem and return None."""
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return None
    configure_logging(settings.log_level)
    return settings


def measure_host_load() -> HostLoad:
    """The 1-minute load average and CPU count right now, so results can say how busy the machine was."""
    return HostLoad(os.getloadavg()[0], os.cpu_count() or 1)


def build_table(settings: Settings) -> PostgresLabTable:
    """The events table adapter."""
    return PostgresLabTable(settings.postgres)


def build_scenarios(settings: Settings, pause: Callable[[float], None], should_stop: Callable[[], bool]) -> Scenarios:
    """Wire the scenarios to their PostgreSQL adapters: the one place that knows which implementations are in use."""
    return Scenarios(
        table=build_table(settings),
        locks=PostgresLockExperiments(settings.postgres),
        changes=PostgresSchemaChanges(settings.postgres, settings.sql_dir),
        flip=PostgresPlanFlip(settings.postgres, settings.sql_dir),
        pause=pause,
        should_stop=should_stop,
    )
```

`load_settings()` is the start-up described in the command-line note. `measure_host_load()` calls `os.getloadavg()[0]` and `os.cpu_count() or 1`. `build_table` and `build_scenarios` are the **composition root**: `build_scenarios(settings, pause, should_stop)` creates the four PostgreSQL adapters and hands them to `Scenarios`; it is the one place that knows which implementations are in use.

## Try it yourself

1. `.venv/bin/python -c "from locks_lab.domain.backfill import id_ranges; print(list(id_ranges(1, 5, 2)))"` prints `[(1, 2), (3, 4), (5, 5)]`.
2. `.venv/bin/python -c "from locks_lab.domain.stats import percentile; print(percentile(list(range(1, 101)), 0.99), percentile([], 0.99), percentile([5, 1, 3], 0.5))"` prints `99 0.0 3`.
3. `.venv/bin/python -c "from locks_lab.domain.stats import Bar, WindowSummary as W; w = lambda p99, e=0, s=0: W(1, 1, 1, e, 1, p99, 1, 1, s); b = Bar.bracketing(w(5), w(8)); print(b.limit_ms, b.allows(w(15)), b.allows(w(17)), b.allows(w(10, e=1)))"` prints `16.0 True False False`: twice the higher baseline (8) is 16; 15 passes, 17 does not, and any error fails.
4. `.venv/bin/python -c "from locks_lab.domain.flip import parse_flip_plan; print(parse_flip_plan(open('sql/explain/f1_stale_statistics.txt').read().splitlines()))"` prints a `FlipPlan(estimate=1, nodes=('Sort', 'Seq Scan'), milliseconds=...)`.
5. `make test` runs the unit tests of all these modules without a database.

## Mistakes people make

- Mixing tabs and spaces for indentation.
- Using a mutable default (`def f(x=[])`): the same list is shared by every call.
- Comparing with `is` where `==` was meant.
- Forgetting that a `list` assigned to a second name is the same list.
- Catching `Exception` and hiding bugs.
- Using `==` to compare floats exactly.

**How this repository avoids them.** Defaults are never mutable (lambda defaults and tuples). Errors are specific classes. Dataclasses are frozen. Generators produce ranges lazily. Every module has a docstring (ruff `D100`). The domain and application contain no threads and no SQL: import-linter checks it.

## Check yourself

1. What does `if __name__ == "__main__":` guard? *Code that must run only when the file is started as a program, not when imported.*
2. What does the `*` in `def f(a, *, b)` mean? *Everything after it, here `b`, can only be passed by name.*
3. What does `with open(path) as f:` guarantee? *The file is closed when the block ends, also if an error is raised.*
4. What is the difference between a list and a tuple? *A list can be changed after creation; a tuple cannot.*
5. What does `raise Error("x") from cause` add? *It records `cause` as the original reason, so the traceback shows both.*

## Further reading

- The Python Tutorial (3.13): https://docs.python.org/3.13/tutorial/index.html
- Language Reference, "Compound statements" and "Expressions": https://docs.python.org/3.13/reference/index.html
- This repository requires Python 3.12 or newer (`requires-python = ">=3.12"`) and was run on 3.13.12; CI uses 3.12.

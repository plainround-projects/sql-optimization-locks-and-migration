# pytest

## What it is

**pytest** is a Python tool for writing and running **tests**: small functions that check that your code does what you think. You write a function whose name starts with `test_`, use the plain Python statement `assert condition` inside it, and run `pytest`. It finds all test functions, runs them, and reports which passed and which failed, with the values involved in the failing `assert`.

## Why this repository uses it

Every "Done when" line of the lesson is a test, and every rule of the quality bar that can be tested is tested. There are 90 unit tests (no database, no threads, about two seconds), 13 integration tests (the real database with the load running) and 3 end-to-end tests (the commands).

## Where it appears

| File | Role |
|---|---|
| `pyproject.toml` | `[tool.pytest.ini_options]`: where tests are, flags, markers. |
| `tests/unit/` | Fast tests of `domain`, `application`, `infrastructure` (without a database) and `interfaces`. |
| `tests/unit/application/fakes.py` | The fake load, table, lock experiments, schema changes, plan flip and store. |
| `tests/integration/conftest.py`, `test_lesson_outcomes.py` | Tests against the seeded database with the load script running. |
| `tests/e2e/test_replay.py` | The commands as subprocesses. |
| `Makefile` | `test`, `test-integration`, `test-e2e`. |

## How it works underneath

**Discovery.** pytest walks the folders given (or `testpaths` from the configuration) and imports every file named `test_*.py` or `*_test.py`. In each it collects functions named `test_*` (and methods of classes named `Test*`).

**Assertions.** `assert a == b`. pytest rewrites the statement when it imports the test file so that, on failure, it prints what `a` and `b` were. Passing means the function returns without an error.

**Expected errors.** `with pytest.raises(SomeError, match="text"):` passes only if the block raises that error and its message matches the regular expression.

**Fixtures.** A **fixture** is a function marked `@pytest.fixture` that prepares something a test needs. A test asks for it by writing the fixture's name as a parameter, and pytest runs the fixture first and passes in the result. A fixture that uses `yield value` hands the value to the test and runs the code after `yield` as clean-up when the test ends. `scope="session"` creates the fixture once per run instead of once per test. Fixtures placed in a file called **`conftest.py`** are available to all tests in that folder and below.

**Built-in fixtures used here.**

- `tmp_path`: a fresh empty temporary folder (a `Path`) for each test.
- `monkeypatch`: changes things for one test and undoes them afterwards: `setenv`/`delenv` (environment variables), `setattr(obj, "name", value)` (replace an attribute).
- `capsys`: captures what the test prints; `capsys.readouterr()` returns `.out` and `.err`.

**Parametrization.** `@pytest.mark.parametrize("name", [v1, v2, ...])` runs the same test once per value.

**Markers.** `@pytest.mark.integration` tags a test; `pytestmark = pytest.mark.integration` at the top of a file tags all tests in it. `pytest -m integration` runs only the tagged tests. `--strict-markers` makes an unknown marker an error (catching typos); markers are declared in the configuration.

**Fakes.** A test double is a simple object that stands in for something heavy (a database). Tests of the use cases pass a **fake** with the same methods, so they run in milliseconds with no database.

**Test levels.** *Unit* tests check one piece with fakes. *Integration* tests use the real database. *End-to-end* tests start the real program and check its output and exit code.

**Reading the output.** `.` passed, `F` failed, `E` error in set-up, `s` skipped. The last line is the summary: `72 passed in 0.32s`. `-ra` adds a summary of every non-passing test. `-q` is quiet.

## Walkthrough of this repository's use

### Configuration

`pyproject.toml`, lines 58 to 64:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "integration: needs PostgreSQL from docker-compose.yml with the seeded events table (make up db)",
    "e2e: replays the lesson through the command-line program against PostgreSQL",
]
```

`testpaths = ["tests"]`; `addopts = "-ra --strict-markers"` (`-ra` prints a summary line for every test that did not simply pass; `--strict-markers` rejects unknown markers); the two markers `integration` and `e2e` are declared with a description (`pytest --markers` shows them). `make test` runs `tests/unit` only; the other two targets select by marker.

### Plain unit tests of the arithmetic

`tests/unit/domain/test_stats.py`, lines 1 to 48:

```python
import pytest

from locks_lab.domain.stats import STALL_MS, Bar, Sample, Tick, make_tick, percentile, summarize


def sample(at: float, ms: float, ok: bool = True) -> Sample:
    return Sample(at, "insert", ms, ok)


def test_percentile_is_nearest_rank():
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.5) == 3.0
    assert percentile(list(map(float, range(1, 101))), 0.99) == 99.0


def test_percentile_of_nothing_is_zero_and_of_one_value_is_that_value():
    assert percentile([], 0.99) == 0.0
    assert percentile([7.0], 0.99) == 7.0


def test_a_tick_counts_finished_statements_and_the_age_of_those_still_waiting():
    samples = [sample(10.2, 2.0), sample(10.7, 4.0, ok=False), sample(9.0, 99.0)]
    tick = make_tick(11.0, 10.0, samples, [3000.0])
    assert (tick.ops, tick.errors) == (2, 1)
    assert tick.p99_ms == 3000.0, "a stalled operation shows even though it has not finished"
    assert tick.oldest_inflight_ms == 3000.0


def test_a_quiet_second_has_a_zero_tick():
    assert make_tick(11.0, 10.0, [], []) == Tick(11.0, 0, 0, 0.0, 0.0)


def test_a_window_summary_covers_what_finished_inside_it():
    samples = [sample(1.0, 2.0), sample(1.5, 4.0), sample(2.5, 6.0, ok=False), sample(9.0, 500.0)]
    ticks = [Tick(2.0, 2, 0, 4.0, 0.0), Tick(3.0, 1, 1, 6.0, 0.0), Tick(10.0, 0, 0, 999.0, 0.0)]
    summary = summarize(samples, ticks, 0.0, 4.0)
    assert (summary.ops, summary.errors, summary.max_ms) == (3, 1, 6.0)
    assert summary.ops_per_second == 0.8
    assert summary.worst_second_p99_ms == 6.0, "the tick at t=10 is outside the window"


def test_a_stalled_second_is_one_where_an_operation_waited_half_a_second():
    ticks = [Tick(1.0, 0, 0, 0.0, STALL_MS), Tick(2.0, 5, 0, 1.0, STALL_MS - 1), Tick(3.0, 0, 0, 0.0, 3000.0)]
    assert summarize([], ticks, 0.0, 4.0).stalled_seconds == 2


def test_a_tick_belongs_to_the_window_its_midpoint_is_in():
    assert summarize([], [Tick(5.4, 0, 0, 9.0, 0.0)], 5.0, 6.0).worst_second_p99_ms == 0.0
    assert summarize([], [Tick(5.6, 0, 0, 9.0, 0.0)], 5.0, 6.0).worst_second_p99_ms == 9.0
```

`sample(at, ms, ok=True)` is a small helper that builds a `Sample`. The tests are plain `assert`s on numbers: `percentile` is the nearest rank (`== 3.0`, `== 99.0`); a tick counts finished statements *and* the age of those still waiting (`assert tick.p99_ms == 3000.0, "a stalled operation shows even though it has not finished"` — the string after the comma is the message printed if the assertion fails); a window summary counts what finished inside it and ignores a tick outside; and a tick belongs to the window its midpoint is in (a tick at t=5.4 has its midpoint at 4.9, outside the window from 5.0 to 6.0; a tick at t=5.6 has its midpoint at 5.1, inside). Test names are full sentences, so a failure reads like a message.

### Fakes for the ports

`tests/unit/application/fakes.py`, lines 1 to 80:

```python
"""In-memory stand-ins for the ports, so the scenarios can be tested without a database or threads."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from locks_lab.domain.locks import LockReport, LockRequest, LockSnapshot, WaitingSession
from locks_lab.domain.outcomes import (
    ConflictOutcome,
    FlipOutcome,
    InterruptedBuild,
    QueueOutcome,
    RebuiltIndex,
    TableSize,
)
from locks_lab.domain.stats import WindowSummary


def window(
    p99: float = 5.0, *, errors: int = 0, stalled: int = 0, ops: int = 100, max_ms: float = 20.0
) -> WindowSummary:
    return WindowSummary(10.0, ops, ops / 10, errors, 1.0, p99, max_ms, p99, stalled)


class FakeLoad:
    """A load whose windows are scripted; records the marks and how long it was asked to run."""

    def __init__(self, windows: Sequence[WindowSummary] | None = None) -> None:
        self.marks: list[str] = []
        self.measured: list[float] = []
        self._clock = 0.0
        self._windows = list(windows or [])

    def now(self) -> float:
        self._clock += 1.0
        return self._clock

    def mark(self, label: str) -> None:
        self.marks.append(label)

    def summary(self, start: float, end: float) -> WindowSummary:
        return self._windows.pop(0) if self._windows else window()

    def measure(self, seconds: float) -> WindowSummary:
        self.measured.append(seconds)
        return self.summary(0.0, seconds)


class FakeTable:
    """Counts resets; the first size read is the clean table, later ones the table after the backfill."""

    def __init__(self) -> None:
        self.resets = 0
        self._size_reads = 0

    def reset(self) -> None:
        self.resets += 1

    def row_count(self) -> int:
        return 2_000_000

    def size(self) -> TableSize:
        self._size_reads += 1
        return TableSize("194 MB", 0) if self._size_reads == 1 else TableSize("357 MB", 1_368_325)


SNAPSHOT = LockSnapshot(
    waiting=(WaitingSession(391, "naive-alter", (390,), 3.0, "ALTER TABLE events ADD COLUMN flagged boolean"),),
    queue=(
        LockRequest(390, "long-transaction", "AccessShareLock", True),
        LockRequest(391, "naive-alter", "AccessExclusiveLock", False),
    ),
)


class FakeLocks:
    def __init__(self) -> None:
        self.holds: list[float] = []
        self.timeouts: list[str] = []

```

`window(...)` builds a `WindowSummary` with defaults. `FakeLoad` implements the same four methods as the `LoadGenerator` port, but its windows are **scripted**: `summary` pops the next prepared window off a list; `now()` advances a counter; it records marks and measured durations. `FakeTable` counts resets and returns a different `TableSize` the second time it is asked (the table "after the backfill"). The later part of the file (lines 82 to 164) has `FakeLocks`, `FakeChanges` (it records the order of calls, and its backfill honours the stop callback), `FakeFlip` (returns canned plan lines) and `RecordingStore`. With them, the whole lesson runs in milliseconds with no database and no threads.

`tests/unit/application/test_scenarios.py`, lines 1 to 23:

```python
from locks_lab.application.scenarios import SETTLE_SECONDS, Scenarios

from .fakes import FakeChanges, FakeFlip, FakeLoad, FakeLocks, FakeTable, window


def build(**options):
    changes, locks, pauses = FakeChanges(), FakeLocks(), list[float]()
    scenarios = Scenarios(
        table=FakeTable(), locks=locks, changes=changes, flip=FakeFlip(), pause=pauses.append, **options
    )
    return scenarios, changes, locks, pauses


def test_the_lock_queue_reports_the_snapshot_the_pile_up_window_and_the_recovery():
    scenarios, _changes, locks, _pauses = build()
    load = FakeLoad([window(3000.0, errors=5, stalled=6), window(4.0)])
    result = scenarios.lock_queue(load, hold_seconds=4)
    assert locks.holds == [4]
    assert result.during.p99_ms == 3000.0
    assert result.after.p99_ms == 4.0
    assert load.measured == [3], "three seconds of load after the long read is released"
    assert result.snapshot.request_of(391) is not None

```

`build(**options)` creates a `Scenarios` over the fakes and returns the pieces. `pause=pauses.append` passes the *list's append method* as the pause function, so the test can check how long the use case asked to wait (`pauses == [SETTLE_SECONDS]`) without waiting. `list[float]()` creates an empty typed list. In the first test, `FakeLoad([window(3000.0, errors=5, stalled=6), window(4.0)])` scripts two windows: the pile-up and the recovery.

### The replay's order of steps

`tests/unit/application/test_replay.py`, lines 29 to 60:

```python
def test_the_steps_run_in_the_lessons_order():
    replay, _load, _table, _store, changes = build()
    replay.run()
    assert changes.calls == [
        "add_flagged_column",
        "backfill 2000 0.05",
        "plain_index_build",
        "interrupted_concurrent_build",
        "rebuild_invalid_index",
        "naive_set_not_null",
        "not_null_in_three_moves",
    ]


def test_every_step_is_marked_in_the_load_record():
    replay, load, *_ = build()
    replay.run()
    assert [mark.split(":")[0] for mark in load.marks] == [
        "reset to the seed's rows",
        "step 1",
        "step 2",
        "step 3",
        "step 4",
        "step 5",
        "step 6",
        "closing baseline",
    ]


def test_the_baseline_and_the_closing_baseline_are_measured_at_the_configured_lengths():
    replay, load, *_ = build()
    replay.run()
```

(The test file builds a `ReplayLesson` over the fakes.) The tests check the order of the steps, that each step is marked in the load's record, that the baseline and the closing baseline are measured at the configured lengths, and that the table is reset before the lesson and after each experiment that leaves something behind.

### monkeypatch, capsys and tmp_path

`tests/unit/interfaces/test_cli.py`, lines 8 to 45:

```python
def test_a_missing_password_is_a_configuration_error_with_exit_code_2_for_every_program(monkeypatch, capsys):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    assert health_cli.main([]) == 2
    assert run_cli.main([]) == 2
    assert load_cli.main([]) == 2
    assert "PGPASSWORD" in capsys.readouterr().err


class FailingProbe:
    name = "postgres"

    def __init__(self, _settings) -> None:
        pass

    def check(self) -> str:
        raise ProbeFailedError("the events table is empty or not seeded; run make db")


class PassingProbe(FailingProbe):
    def check(self) -> str:
        return "2,000,000 events"


def test_health_is_exit_1_when_the_probe_fails(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setattr(health_cli, "PostgresEventsProbe", FailingProbe)
    assert health_cli.main([]) == 1
    assert "FAIL postgres: the events table is empty" in capsys.readouterr().out


def test_health_is_exit_0_when_the_probe_passes(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setattr(health_cli, "PostgresEventsProbe", PassingProbe)
    assert health_cli.main([]) == 0
    assert "ok postgres: 2,000,000 events" in capsys.readouterr().out


class FakeReplay:
```

`monkeypatch.delenv("PGPASSWORD", raising=False)` removes an environment variable for the test; `monkeypatch.setenv` sets one. `capsys.readouterr().err` is what the command wrote to standard error. Small classes `Failing` and `Passing` stand in for the probe and `monkeypatch.setattr(health_cli, "PostgresEventsProbe", Failing)` replaces the name inside the `health_cli` module for this test only. The tests for exit codes 130 and 1 and for the printed verdict (lines 79 to 103) replace the replay's collaborators the same way; `tmp_path` gives a fresh folder per test.

### Other unit test files

- `domain/test_locks_backfill_flip.py`: the lock snapshot (lookups by application and pid, the printed form), `id_ranges` (`[(1, 4), (5, 8), (9, 10)]`, exact multiples, an empty range) and the plan parser.
- `domain/test_host.py`: `HostLoad`.
- `application/test_report.py`, `test_health.py`: exact table rows; a tiny probe class.
- `infrastructure/test_retry.py`, `test_logging_and_shutdown.py`, `test_settings.py`, `test_sql_script.py`, `test_artifacts.py`: as described in their notes (a `Flaky` callable; an in-memory stream; a real signal; parametrized bad settings; dollar-quoted bodies).

### The unit tests that every repository shares, line by line

Three of the lab's helper modules are the same in all three repositories: the retry helper, the "how busy was the machine" note, the logging and shutdown helpers, and the health check. Their tests are the same too. This part walks through each file completely. Before the first one, three ideas that every test below uses.

- **A test is a function whose name starts with `test_`.** pytest finds it, calls it with no arguments, and counts it as passed if it returns normally and failed if anything inside it raises an error.
- **`assert` is a Python statement that raises an `AssertionError` when its condition is false.** Everything that "checks" something in these files is an `assert`, or a `with pytest.raises(...)` block that checks that an error does happen.
- **A test double is a stand-in object.** Instead of really sleeping for seconds, or really asking a database a question, a test hands the code under test a small replacement that records what it was asked, so the test is fast and gives the same answer every time.

#### `tests/unit/infrastructure/test_retry.py`

The code under test is `retry`, a function that calls an operation, and if the operation fails with one of a list of error types, waits a moment and tries again. The wait doubles after each failure (1 second, 2 seconds, 4 seconds, and so on) and is then multiplied by a random number between 0.5 and 1.0. That random part is called **jitter**: it stops many clients that failed at the same moment from all retrying at the same moment.

`tests/unit/infrastructure/test_retry.py`, lines 1 to 5:

```python
import random

import pytest

from locks_lab.infrastructure.retry import retry
```

Line 1 imports Python's `random` module, which supplies random numbers and, in the next lines, a random number generator we can seed. Line 3 imports `pytest`, which is needed for `pytest.raises`. Line 5 imports the function under test from the lab's own package. A blank line separates the three groups: the standard library, third-party packages, and this project's own code. That is the order the linter `ruff` enforces.

`tests/unit/infrastructure/test_retry.py`, lines 8 to 16:

```python
class Flaky:
    def __init__(self, failures: int) -> None:
        self.failures, self.calls = failures, 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("down")
        return "ok"
```

`Flaky` is a hand-made test double: an operation that fails a chosen number of times and then succeeds.

- `class Flaky:` starts a class, a blueprint for objects.
- `def __init__(self, failures: int) -> None:` is the constructor; Python runs it when you write `Flaky(3)`. `self` is the object being built. `: int` says the argument is a whole number and `-> None` says the function returns nothing; these are type hints that `mypy` checks but Python ignores while running.
- `self.failures, self.calls = failures, 0` stores two values on the object in one line: how many failures to produce, and a counter of calls so far, starting at zero.
- `def __call__(self) -> str:` is a special method name. It makes an object callable, so `Flaky(3)()` runs this method, exactly as if the object were a function. That is what lets `retry` take a `Flaky` where it expects an operation.
- `self.calls += 1` adds one to the counter every time the object is called.
- `if self.calls <= self.failures:` is true for the first `failures` calls, and then `raise ConnectionError("down")` stops the call with an error of that type. `ConnectionError` is a built-in Python error, the kind a database driver raises when the network drops.
- `return "ok"` is reached only on the later calls, which succeed.

`tests/unit/infrastructure/test_retry.py`, lines 19 to 22:

```python
def test_it_returns_the_first_success_without_sleeping():
    pauses: list[float] = []
    assert retry(Flaky(0), attempts=3, base_delay_seconds=1, retry_on=(ConnectionError,), sleep=pauses.append) == "ok"
    assert pauses == []
```

The first test: an operation that never fails (`Flaky(0)`) must come back with its answer and never wait. `pauses: list[float] = []` creates an empty list that will collect every pause the retry helper asks for. The argument `sleep=pauses.append` is the trick: `retry` normally calls `time.sleep` to wait, but here it is told to call `pauses.append` instead, which records the number and returns at once. The call also passes `attempts=3` (give up after three tries), `base_delay_seconds=1` (the first pause would be about one second) and `retry_on=(ConnectionError,)` (the tuple of error types that deserve a retry; the trailing comma makes it a one-item tuple). The line ends with `== "ok"`, so the `assert` checks the returned value. The second `assert` checks that the list of pauses is still empty.

`tests/unit/infrastructure/test_retry.py`, lines 25 to 39:

```python
def test_it_retries_with_doubling_pauses_inside_the_jitter_band():
    pauses: list[float] = []
    operation = Flaky(3)
    result = retry(
        operation,
        attempts=5,
        base_delay_seconds=1,
        retry_on=(ConnectionError,),
        sleep=pauses.append,
        rng=random.Random(1),
    )
    assert result == "ok"
    assert operation.calls == 4
    for pause, ceiling in zip(pauses, (1, 2, 4), strict=True):
        assert ceiling * 0.5 <= pause <= ceiling
```

The second test checks the doubling and the jitter band. `Flaky(3)` fails three times, so the fourth call succeeds. The call is spread over several lines because each argument is on its own line, which is how the formatter lays out a call that is too long for one line. `rng=random.Random(1)` hands `retry` a random number generator started with the **seed** 1. A seeded generator produces the same sequence every run, so the test cannot fail by bad luck. The asserts check that the final answer is `"ok"` and that `operation.calls == 4` (three failures plus the success). The loop `for pause, ceiling in zip(pauses, (1, 2, 4), strict=True):` walks the three recorded pauses together with the three values they may not exceed. `zip` pairs items from two sequences; `strict=True` makes `zip` raise an error if the two sequences have different lengths, which would mean `retry` slept the wrong number of times. Inside the loop, `assert ceiling * 0.5 <= pause <= ceiling` is Python's chained comparison: each pause must be at least half of its ceiling and at most the ceiling, which is the jitter band.

`tests/unit/infrastructure/test_retry.py`, lines 42 to 52:

```python
def test_the_pause_is_capped():
    pauses: list[float] = []
    retry(
        Flaky(4),
        attempts=6,
        base_delay_seconds=10,
        retry_on=(ConnectionError,),
        sleep=pauses.append,
        max_delay_seconds=15,
    )
    assert max(pauses) <= 15
```

The third test checks the cap. With a base delay of 10 seconds the doubled values would be 10, 20, 40 and 80, which is far too long to wait. `max_delay_seconds=15` tells `retry` never to pause longer than 15 seconds before the jitter is applied. `Flaky(4)` fails four times and `attempts=6` leaves room for the fifth call to succeed, so four pauses are recorded. `assert max(pauses) <= 15` takes the largest recorded pause and checks it against the cap. The test does not need a seeded generator, because jitter only shrinks a pause, so the bound holds for every random value.

`tests/unit/infrastructure/test_retry.py`, lines 55 to 59:

```python
def test_the_last_failure_is_raised_after_the_final_attempt():
    operation = Flaky(10)
    with pytest.raises(ConnectionError):
        retry(operation, attempts=3, base_delay_seconds=0, retry_on=(ConnectionError,), sleep=lambda _: None)
    assert operation.calls == 3
```

The fourth test checks what happens when every attempt fails. `Flaky(10)` fails ten times but only three attempts are allowed. `with pytest.raises(ConnectionError):` says "the code inside this block must raise a `ConnectionError`; if it raises nothing, or a different error, the test fails". The pause is `base_delay_seconds=0` and `sleep=lambda _: None` is a one-line function that takes one argument, named `_` because it is ignored, and does nothing; the test does not need to see the pauses, only to avoid waiting. After the block, `assert operation.calls == 3` proves the helper stopped after exactly three tries and raised the last error instead of looping on.

`tests/unit/infrastructure/test_retry.py`, lines 62 to 67:

```python
def test_other_errors_are_not_retried():
    def broken() -> str:
        raise KeyError("x")

    with pytest.raises(KeyError):
        retry(broken, attempts=3, base_delay_seconds=0, retry_on=(ConnectionError,), sleep=lambda _: None)
```

The fifth test checks that only the listed errors are retried. `broken` is a small function defined inside the test that always raises `KeyError("x")`. `retry_on` lists only `ConnectionError`, so a `KeyError` must not be caught: it must come straight out. The blank line after the function is required by the formatter. If `retry` had retried it, the test would still pass the error out after three tries, so the point here is the type: `pytest.raises(KeyError)` shows the original error, not a wrapped one, escapes.

`tests/unit/infrastructure/test_retry.py`, lines 70 to 80:

```python
def test_each_retry_is_reported():
    seen: list[int] = []
    retry(
        Flaky(2),
        attempts=4,
        base_delay_seconds=0,
        retry_on=(ConnectionError,),
        sleep=lambda _: None,
        on_retry=lambda attempt, _: seen.append(attempt),
    )
    assert seen == [1, 2]
```

The sixth test checks the `on_retry` hook, a function `retry` calls before each pause with the attempt number and the error. `seen: list[int] = []` collects the attempt numbers. `on_retry=lambda attempt, _: seen.append(attempt)` is a function that takes two arguments (the second is ignored) and records the first. With `Flaky(2)` the first two calls fail, so the hook is called for attempts 1 and 2 and not for the third, which succeeds. `assert seen == [1, 2]` checks exactly that.

`tests/unit/infrastructure/test_retry.py`, lines 83 to 85:

```python
def test_at_least_one_attempt_is_required():
    with pytest.raises(ValueError, match="attempts"):
        retry(Flaky(0), attempts=0, base_delay_seconds=0, retry_on=(ConnectionError,))
```

The last test checks the guard at the top of `retry`. Asking for zero attempts makes no sense, so the helper raises `ValueError`. `match="attempts"` is a regular expression that pytest searches for in the error's message; it makes sure the message names the bad argument. This call leaves out `sleep` because the helper must fail before it could ever sleep.

#### `tests/unit/domain/test_host.py`

The code under test is `HostLoad`, a small value object that holds the machine's load average (how many programs were waiting for a processor, averaged over the last minute) and the number of processors. It marks the machine as loaded when the load average is more than half the processor count. The lab prints a note about this next to every timing, because milliseconds measured on a busy computer are inflated.

`tests/unit/domain/test_host.py`, lines 1 to 1:

```python
from locks_lab.domain.host import HostLoad
```

The only import: the class under test. The `domain` folder never imports a database driver or the file system, which is why this test needs no setup at all.

`tests/unit/domain/test_host.py`, lines 4 to 7:

```python
def test_a_load_above_half_a_task_per_cpu_is_a_loaded_machine():
    assert HostLoad(40.0, 12).loaded
    assert not HostLoad(3.0, 12).loaded
    assert not HostLoad(6.0, 12).loaded
```

`HostLoad(40.0, 12)` builds a value with load average 40 and 12 CPUs. 40 is more than half of 12, so `.loaded` must be true and the first `assert` passes. `assert not HostLoad(3.0, 12).loaded` uses `not` to say the opposite: 3 is below 6, so the machine is not loaded. The third line tests the boundary: 6.0 on 12 CPUs is exactly half, and the rule is "more than half", so `loaded` is false. Testing the exact boundary is how a mistaken `>=` is caught.

`tests/unit/domain/test_host.py`, lines 10 to 14:

```python
def test_the_note_names_the_load_and_says_what_to_do_when_it_is_high():
    loaded = HostLoad(39.5, 12).note()
    assert "loaded machine (load average 39.5 on 12 CPUs)" in loaded
    assert "rerun `make run`" in loaded
    assert HostLoad(2.0, 12).note() == "Measured at load average 2.0 on 12 CPUs."
```

The second test checks the sentence written into the results file. `HostLoad(39.5, 12).note()` returns the loaded-machine message. `assert "..." in loaded` checks that a piece of text appears inside a longer text, which keeps the test from breaking if the wording around it changes. The two pieces checked are the measured numbers, `loaded machine (load average 39.5 on 12 CPUs)`, and the advice to rerun `make run`; the backticks around `make run` are part of the Markdown the note produces. The last line uses `==` because the quiet-machine sentence is short and fixed: `Measured at load average 2.0 on 12 CPUs.` has to match exactly.

#### `tests/unit/application/test_health.py`

The code under test is `check_health`, which takes a list of **probes** (objects with a `name` and a `check()` method that either returns a short text or raises `ProbeFailedError`) and returns a report that is healthy only if every probe passed. A failing probe must be reported, not allowed to crash the check.

`tests/unit/application/test_health.py`, lines 1 to 1:

```python
from locks_lab.application.health import ProbeFailedError, check_health
```

Imports the error class and the function. `ProbeFailedError` is imported because the test double raises it.

`tests/unit/application/test_health.py`, lines 4 to 11:

```python
class Probe:
    def __init__(self, name: str, error: str | None = None) -> None:
        self.name, self._error = name, error

    def check(self) -> str:
        if self._error:
            raise ProbeFailedError(self._error)
        return "fine"
```

`Probe` is the test double. Its constructor takes a `name` and an optional `error` text (`str | None` means "text or nothing", default `None`). `self.name, self._error = name, error` stores both; the leading underscore on `_error` is a convention for "internal, do not touch from outside". The `check` method raises `ProbeFailedError` with the stored text if one was given, and otherwise returns the word `fine`. `if self._error:` is true for any non-empty text.

`tests/unit/application/test_health.py`, lines 14 to 17:

```python
def test_all_probes_passing_is_healthy():
    report = check_health([Probe("a"), Probe("b")])
    assert report.healthy
    assert [r.detail for r in report.results] == ["fine", "fine"]
```

With two passing probes the report must be healthy. The second `assert` uses a **list comprehension**, `[r.detail for r in report.results]`, which builds a list by taking the `detail` of every result, and compares it with `["fine", "fine"]`.

`tests/unit/application/test_health.py`, lines 20 to 23:

```python
def test_one_failing_probe_is_reported_and_makes_the_report_unhealthy():
    report = check_health([Probe("a"), Probe("b", "down")])
    assert not report.healthy
    assert [(r.name, r.ok, r.detail) for r in report.results] == [("a", True, "fine"), ("b", False, "down")]
```

With one failing probe, the report must not be healthy and must still contain both results in order. The comprehension here builds one tuple per result, `(r.name, r.ok, r.detail)`, and the expected list shows that probe `a` passed with `fine` and probe `b` failed with the message `down`. That the second result exists at all proves the failing probe did not stop the loop.

#### `tests/unit/infrastructure/test_logging_and_shutdown.py`

Two helpers are tested here. `configure_logging` makes every log record come out as one line of **logfmt**, a plain-text format of `key=value` pairs separated by spaces. `ShutdownSignal` is a flag that Ctrl-C (the `SIGINT` signal) or `SIGTERM` sets, so a long loop can notice the request and stop cleanly between two units of work. A **signal** is a small message the operating system sends to a running program; `SIGINT` is what Ctrl-C sends and `SIGTERM` is what `kill` and `docker stop` send by default.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 1 to 6:

```python
import io
import logging
import signal

from locks_lab.infrastructure.logging import configure_logging, fields
from locks_lab.infrastructure.shutdown import ShutdownSignal
```

`io` is the standard library module for streams; `io.StringIO` is a fake file that keeps its text in memory. `logging` is the standard logging module. `signal` gives access to operating-system signals. The last two imports bring in the lab's helpers: `configure_logging` and `fields` (which attaches key and value pairs to a log call), and the `ShutdownSignal` class.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 9 to 19:

```python
def test_a_record_becomes_one_logfmt_line_with_its_fields():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    logging.getLogger("demo").info("partitions assigned", extra=fields(member="consumer-1", partitions=[0, 1]))
    line = stream.getvalue().strip()
    assert line.startswith("ts=")
    assert "level=INFO" in line
    assert "logger=demo" in line
    assert 'msg="partitions assigned"' in line
    assert "member=consumer-1" in line
    assert 'partitions="[0, 1]"' in line
```

The first test follows one log call from start to finish. `stream = io.StringIO()` is a text buffer standing in for the terminal. `configure_logging("INFO", stream)` tells the logging system to show records of level `INFO` and above and to write them to that buffer in logfmt. `logging.getLogger("demo")` returns the logger named `demo`; `.info("partitions assigned", extra=fields(member="consumer-1", partitions=[0, 1]))` writes one record with extra pairs. `stream.getvalue().strip()` reads everything written so far and removes the trailing newline. The asserts check each piece of the line: it starts with `ts=` (the timestamp), contains `level=INFO` and `logger=demo`, the message in quotes because it contains a space (`msg="partitions assigned"`), the plain pair `member=consumer-1`, and the list shown as text in quotes (`partitions="[0, 1]"`) because its text contains a space.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 22 to 26:

```python
def test_records_below_the_level_are_dropped_():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    logging.getLogger("demo").debug("hidden")
    assert stream.getvalue() == ""
```

A `DEBUG` message is less important than the `INFO` threshold, so it must be dropped: the buffer must still be an empty string.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 29 to 37:

```python
def test_an_exception_is_attached_to_the_line():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("demo").exception("failed")
    assert "exc=" in stream.getvalue()
    assert "boom" in stream.getvalue()
```

When code logs from inside an `except` block with `.exception(...)`, the log line has to carry the error. The test raises a `ValueError` on purpose inside `try:`, catches it with `except ValueError:`, and logs there. It then checks that the line has an `exc=` pair and that the word `boom`, the error's message, appears in it.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 40 to 45:

```python
def test_configuring_twice_does_not_duplicate_lines():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    configure_logging("INFO", stream)
    logging.getLogger("demo").info("once")
    assert stream.getvalue().count("msg=once") == 1
```

Calling `configure_logging` twice must not make every message appear twice. The helper replaces the list of handlers on the root logger (a **handler** is the part of the logging system that sends a record somewhere), and this test proves it: after two calls one `info("once")` produces exactly one `msg=once`, counted with the string method `.count(...)`.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 48 to 52:

```python
def test_a_shutdown_signal_starts_unset_and_is_set_by_request():
    shutdown = ShutdownSignal()
    assert not shutdown.requested
    shutdown.request()
    assert shutdown.requested
```

A new `ShutdownSignal` starts with its flag down (`requested` is false) and `request()` raises it. The class stores the flag in a `threading.Event`, a thread-safe on/off switch, and this test checks the public behavior without caring how it is stored.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 55 to 64:

```python
def test_sigterm_sets_the_flag_once_installed():
    shutdown = ShutdownSignal()
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        shutdown.install()
        signal.raise_signal(signal.SIGTERM)
        assert shutdown.requested
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
```

The last test sends a real signal to the test process. `signal.getsignal(number)` returns whatever function currently handles that signal; the dictionary comprehension saves the handlers for `SIGINT` and `SIGTERM` in `previous`, because the test is about to replace them and must put them back so that it does not disturb the other tests or pytest itself. `shutdown.install()` registers the helper's handler for both signals. `signal.raise_signal(signal.SIGTERM)` makes the process send itself a `SIGTERM`; the handler runs and sets the flag, so `assert shutdown.requested` passes. The `finally:` block runs whether or not the assert passed, and the loop in it calls `signal.signal(number, handler)` to restore every saved handler.

### The remaining unit tests of this repository, line by line

These are the unit test files that belong to this repository alone, plus the shared fakes they rely on. Each is quoted completely and explained. Two reminders about pytest. **`pytest.raises(SomeError, match="text")`** is a block that passes only if the code inside raises that error and the error's message contains the given text (the `match` value is a regular expression searched in the message). **`@pytest.mark.parametrize("name", [a, b, c])`** placed above a test function runs that function once for each listed value, giving the value to the argument called `name`; each run is reported as its own test.

#### `tests/unit/domain/test_stats.py`, the bar

The lab measures a running load script in one-second **ticks** and summarizes stretches of it as a `WindowSummary` (operations per second, errors, the 50th and 99th **percentile** of the time an operation took, and the number of **stalled** seconds). A percentile is the value below which that share of the measurements fall: the p99 is the time that 99 out of 100 operations beat. A second counts as stalled when an operation had been waiting for 500 ms or more. The **bar** is the lesson's pass mark for a migration: the p99 may be at most twice the baseline (the p99 measured when nothing was being changed), with no errors and no stalled second.

`tests/unit/domain/test_stats.py`, lines 46 to 69:

```python
def test_a_tick_belongs_to_the_window_its_midpoint_is_in():
    assert summarize([], [Tick(5.4, 0, 0, 9.0, 0.0)], 5.0, 6.0).worst_second_p99_ms == 0.0
    assert summarize([], [Tick(5.6, 0, 0, 9.0, 0.0)], 5.0, 6.0).worst_second_p99_ms == 9.0


def test_the_bar_is_twice_the_higher_baseline_and_needs_no_errors_and_no_stall():
    quiet = summarize([sample(0.5, 4.0)], [], 0.0, 1.0)
    noisy = summarize([sample(0.5, 8.0)], [], 0.0, 1.0)
    bar = Bar.bracketing(quiet, noisy)
    assert bar.baseline_p99_ms == 8.0
    assert bar.limit_ms == 16.0
    assert bar.allows(summarize([sample(0.5, 16.0)], [], 0.0, 1.0))
    assert not bar.allows(summarize([sample(0.5, 16.1)], [], 0.0, 1.0))


def test_an_error_or_a_stalled_second_fails_the_bar_even_with_a_low_p99():
    bar = Bar(10.0)
    assert not bar.allows(summarize([sample(0.5, 1.0, ok=False)], [], 0.0, 1.0))
    assert not bar.allows(summarize([sample(0.5, 1.0)], [Tick(1.0, 1, 0, 1.0, 900.0)], 0.0, 1.0))


@pytest.mark.parametrize("factor", [1.0, 3.0])
def test_the_factor_is_configurable(factor):
    assert Bar(10.0, factor).limit_ms == 10.0 * factor
```

The first test of this block decides which window a tick belongs to. A tick is the summary of one second and carries the time it was taken at, `t`. The rule is that a tick belongs to a window when its **midpoint**, `t - 0.5`, lies inside the window. For the window from 5.0 to 6.0 seconds, a tick taken at 5.4 has the midpoint 4.9, which is outside, so its p99 of 9.0 is not counted (the window's `worst_second_p99_ms` is `0.0`), while a tick taken at 5.6 has the midpoint 5.1, inside, so 9.0 is counted. The helper `summarize(samples, ticks, start, end)` takes lists of finished operations and ticks; the empty list `[]` means "no finished operations".

The second test builds two baselines, a quiet one with p99 of 4.0 ms and a noisy one with 8.0 ms, using the test file's `sample(at, ms)` helper, which makes one finished `insert` operation that ended at time `at`. `Bar.bracketing(quiet, noisy)` takes the higher of the two, because other programs on the machine move p99 as much as a migration does. The baseline must be 8.0 and the limit twice that, 16.0. A window with p99 16.0 is allowed (the limit is inclusive) and one with 16.1 is not.

The third test shows that the p99 alone is not enough. With a bar of 10 ms, a window with a very low p99 but one failed operation (`ok=False`) is refused, and so is one with a low p99 whose tick says an operation had been waiting for 900 ms (the fifth field of `Tick`, `oldest_inflight_ms`), which is a stall.

The last test is parametrized with two factors, 1.0 and 3.0. The bar's multiplier is configurable and the limit must be the baseline times the factor, 10.0 times each.

#### `tests/unit/domain/test_locks_backfill_flip.py`

Three small pieces of the domain are tested together because each is short. `LockSnapshot` is a picture of who waits for whom in the database at one moment. `id_ranges` cuts a range of ids into batches for the backfill. `parse_flip_plan` reads the plans of the statistics experiment.

`tests/unit/domain/test_locks_backfill_flip.py`, lines 1 to 19:

```python
import pytest

from locks_lab.domain.backfill import id_ranges
from locks_lab.domain.errors import PlanParseError
from locks_lab.domain.flip import parse_flip_plan
from locks_lab.domain.locks import LockRequest, LockSnapshot, WaitingSession

SNAPSHOT = LockSnapshot(
    waiting=(
        WaitingSession(391, "naive-alter", (390,), 3.0, "ALTER TABLE events ADD COLUMN flagged boolean"),
        WaitingSession(143, "load", (391,), 2.9, "INSERT INTO events"),
        WaitingSession(144, "load", (391,), 2.9, "INSERT INTO events"),
    ),
    queue=(
        LockRequest(390, "long-transaction", "AccessShareLock", True),
        LockRequest(391, "naive-alter", "AccessExclusiveLock", False),
        LockRequest(143, "load", "RowExclusiveLock", False),
    ),
)
```

Imports, then `SNAPSHOT`, a hand-made snapshot of the situation the lesson creates. `waiting` lists the sessions that are blocked: each `WaitingSession` has the process id (`pid`) of the session, its application name, a tuple of the pids it is blocked by, how long it has waited in seconds, and the statement text. Here session 391 (an `ALTER TABLE` run by the lab as `naive-alter`) waits for session 390 for 3.0 seconds, and sessions 143 and 144 (the load script, application name `load`) wait for the ALTER, not for 390. `queue` lists the lock requests in the order PostgreSQL holds them: 390 is a long-running read-only transaction (`long-transaction`) that holds an `AccessShareLock` (`True` means granted), 391 wants an `AccessExclusiveLock` and has not got it (`False`), and 143 wants a `RowExclusiveLock` and is stuck behind it.

`tests/unit/domain/test_locks_backfill_flip.py`, lines 22 to 31:

```python
def test_the_waiting_sessions_of_an_application_are_found_by_name():
    assert [session.pid for session in SNAPSHOT.waiting_application("load")] == [143, 144]
    assert SNAPSHOT.waiting_application("nobody") == ()


def test_the_lock_a_session_holds_or_waits_for_is_found_by_pid():
    request = SNAPSHOT.request_of(391)
    assert request is not None
    assert (request.mode, request.granted) == ("AccessExclusiveLock", False)
    assert SNAPSHOT.request_of(1) is None
```

`waiting_application("load")` returns the waiting sessions of one application name, and the pids come back as `[143, 144]`. For a name nobody uses it returns an empty tuple `()`. `request_of(391)` returns the lock request of a session by pid; the test checks the lock mode `AccessExclusiveLock` and that it is not granted. `assert request is not None` first narrows the type for `mypy` and fails with a clear message if the lookup returned nothing. A pid that is not in the snapshot gives `None`.

`tests/unit/domain/test_locks_backfill_flip.py`, lines 34 to 40:

```python
def test_the_snapshot_prints_both_views_like_the_lessons_notes():
    text = SNAPSHOT.format()
    assert "pg_stat_activity, sessions waiting on a lock" in text
    assert "naive-alter" in text
    assert "[390]" in text
    assert "AccessExclusiveLock" in text
    assert text.endswith("\n")
```

`format()` prints both views the way the lesson's notes show them. The test looks for the heading text `pg_stat_activity, sessions waiting on a lock` (that view lists what each session is doing), the application name, the blocker list `[390]`, the lock mode, and requires that the text ends with a line break.

`tests/unit/domain/test_locks_backfill_flip.py`, lines 43 to 54:

```python
def test_id_ranges_cover_every_id_once_with_the_last_batch_short():
    assert list(id_ranges(1, 10, 4)) == [(1, 4), (5, 8), (9, 10)]


def test_id_ranges_of_an_exact_multiple_and_of_nothing():
    assert list(id_ranges(1, 6, 3)) == [(1, 3), (4, 6)]
    assert list(id_ranges(5, 4, 3)) == []


def test_a_batch_size_below_one_is_refused():
    with pytest.raises(ValueError, match="at least 1"):
        list(id_ranges(1, 10, 0))
```

`id_ranges(first_id, last_id, batch_size)` yields inclusive `(first, last)` pairs. A **generator** is a function that hands out one value at a time; `list(...)` collects them all. For ids 1 to 10 in batches of 4 the ranges are `(1, 4)`, `(5, 8)` and `(9, 10)`: the last batch is shorter. For 1 to 6 in batches of 3 it is exactly `(1, 3)` and `(4, 6)`. When the first id is greater than the last (5 to 4) there is nothing to do and the list is empty. A batch size below one would loop forever, so it raises `ValueError` mentioning `at least 1`; the `list(...)` around the call is needed because a generator does not run (and so does not raise) until something asks it for a value.

`tests/unit/domain/test_locks_backfill_flip.py`, lines 57 to 67:

```python
STALE = [
    "Limit  (cost=87147.68..87147.68 rows=1 width=16) (actual time=198.6..198.7 rows=100.00 loops=1)",
    "  ->  Sort  (cost=87147.68..87147.68 rows=1 width=16) (actual time=198.6..198.6 rows=100.00 loops=1)",
    "        ->  Seq Scan on events  (cost=0.00..87147.67 rows=1 width=16) (actual time=92.1..178.3 rows=150000.00)",
    "Execution Time: 198.721 ms",
]
FIXED = [
    "Limit  (cost=0.43..74.60 rows=100 width=16) (actual time=0.012..0.059 rows=100.00 loops=1)",
    "  ->  Index Scan Backward using idx_events_created_at on events  (cost=0.43..112563.55 rows=151757 width=16)",
    "Execution Time: 0.071 ms",
]
```

`STALE` and `FIXED` are plan texts in the shape of `EXPLAIN (ANALYZE, BUFFERS)` output for the statistics experiment. In `STALE` the planner expected `rows=1` from the scan, so it chose a sequential scan of the whole table (`Seq Scan`) and a `Sort`; the real number of rows was 150,000 (`rows=150000.00` in the actual part). Plan lines are read from the innermost node outward, which is why the Sort sits above the scan. `FIXED` shows the plan after the statistics were corrected: an `Index Scan Backward`, which walks an index from its end so that no sort is needed, with the estimate of 151,757 rows.

`tests/unit/domain/test_locks_backfill_flip.py`, lines 70 to 88:

```python
def test_a_stale_plan_reads_as_one_expected_row_and_a_scan_of_everything():
    plan = parse_flip_plan(STALE)
    assert plan.estimate == 1
    assert plan.nodes == ("Sort", "Seq Scan")
    assert plan.scans_everything
    assert not plan.walks_the_index
    assert plan.milliseconds == 198.721


def test_a_fixed_plan_walks_the_index_with_the_scan_nodes_estimate():
    plan = parse_flip_plan(FIXED)
    assert plan.estimate == 151757
    assert plan.walks_the_index
    assert not plan.scans_everything


def test_a_plan_without_analyze_is_refused():
    with pytest.raises(PlanParseError, match="ANALYZE"):
        parse_flip_plan(["Seq Scan on events  (cost=0.00..1.00 rows=1 width=1)"])
```

The first test reads the stale plan. The estimate is the row count the planner expected on the deepest node (`1`), the nodes are `("Sort", "Seq Scan")` in plan order, the plan counts as scanning everything and as not walking the index, and the time is 198.721 ms. The second reads the fixed plan: the estimate is that of the scan node (151,757), and the plan walks the index and does not scan everything. The third checks that a plan printed without `ANALYZE` (it has estimates but no `Execution Time`) raises `PlanParseError` that mentions `ANALYZE`.

#### `tests/unit/application/fakes.py`, the parts used by the scenarios

The first half of the file, the load, the table and the lock queue snapshot, is quoted in the sections about test doubles above. These are the remaining stand-ins.

`tests/unit/application/fakes.py`, lines 76 to 90:

```python
class FakeLocks:
    def __init__(self) -> None:
        self.holds: list[float] = []
        self.timeouts: list[str] = []

    def lock_queue(self, hold_seconds: float) -> QueueOutcome:
        self.holds.append(hold_seconds)
        return QueueOutcome(SNAPSHOT, hold_seconds)

    def forced_conflict(self, lock_timeout: str) -> ConflictOutcome:
        self.timeouts.append(lock_timeout)
        return ConflictOutcome(True, 1.0)


class FakeChanges:
```

`FakeLocks` stands in for the object that runs the lock experiments. `lock_queue(hold_seconds)` records how long it was asked to hold the long read and returns a `QueueOutcome` holding the module-level `SNAPSHOT` and that time. `forced_conflict(lock_timeout)` records the timeout text it was given and returns a `ConflictOutcome` that says the statement failed fast, `True`, after 1.0 second.

`tests/unit/application/fakes.py`, lines 90 to 129:

```python
class FakeChanges:
    """Records the order of the changes; the backfill honors the stop callback between batches."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def add_flagged_column(self) -> int:
        self.calls.append("add_flagged_column")
        return 1

    def backfill_flagged(self, batch_size: int, pause_seconds: float, should_stop: Callable[[], bool]) -> int:
        self.calls.append(f"backfill {batch_size} {pause_seconds}")
        return 0 if should_stop() else 100

    def unflagged_rows(self) -> int:
        return 0

    def plain_index_build(self) -> float:
        self.calls.append("plain_index_build")
        return 0.8

    def interrupted_concurrent_build(self) -> InterruptedBuild:
        self.calls.append("interrupted_concurrent_build")
        return InterruptedBuild(True, ("idx_events_device_created",), True)

    def rebuild_invalid_index(self) -> RebuiltIndex:
        self.calls.append("rebuild_invalid_index")
        return RebuiltIndex(0.9, True)

    def naive_set_not_null(self) -> LockReport:
        self.calls.append("naive_set_not_null")
        return LockReport(0.18, ("AccessExclusiveLock",))

    def not_null_in_three_moves(self) -> dict[str, LockReport]:
        self.calls.append("not_null_in_three_moves")
        return {
            "add_check_not_valid": LockReport(0.0005, ("AccessExclusiveLock",)),
            "validate": LockReport(0.14, ("ShareUpdateExclusiveLock",)),
            "set_not_null": LockReport(0.0007, ("AccessExclusiveLock",)),
        }
```

`FakeChanges` stands in for the schema changes. Each method appends its name to `calls`, which is how the tests see the order. `add_flagged_column` returns 1, the number of attempts it needed. `backfill_flagged(batch_size, pause_seconds, should_stop)` records its arguments in the text `backfill 2000 0.05` and returns 100 batches, or 0 if the stop callback says to stop (`return 0 if should_stop() else 100`). `unflagged_rows` returns 0 (the backfill finished). `plain_index_build` returns the build time 0.8 seconds. `interrupted_concurrent_build` returns an `InterruptedBuild` that says the build was cancelled, names one invalid index, and says it is maintained but not usable. `rebuild_invalid_index` returns a `RebuiltIndex` of 0.9 seconds that is valid. `naive_set_not_null` returns a `LockReport` of 0.18 seconds holding an `AccessExclusiveLock`. `not_null_in_three_moves` returns a dictionary with one `LockReport` per move: adding the constraint (0.5 ms under an exclusive lock), validating it (140 ms under the weaker `ShareUpdateExclusiveLock`) and setting the column to NOT NULL (0.7 ms under an exclusive lock).

`tests/unit/application/fakes.py`, lines 132 to 148:

```python
STALE = (
    "Sort  (cost=1..2 rows=1 width=1)",
    "  ->  Seq Scan on events  (cost=0..1 rows=1 width=1)",
    "Execution Time: 175.0 ms",
)
INDEXED = (
    "Index Scan Backward using idx_events_created_at on events  (cost=0..1 rows=150000 width=1)",
    "Execution Time: 0.07 ms",
)


class FakeFlip:
    def run(self) -> FlipOutcome:
        return FlipOutcome(
            150_000,
            {"f1_stale_statistics": STALE, "f2_after_analyze": INDEXED, "f3_after_extended_statistics": INDEXED},
        )
```

`STALE` and `INDEXED` are plan texts: the stale one is a `Sort` over a `Seq Scan` taking 175 ms and the indexed one an `Index Scan Backward` with an estimate of 150,000 rows taking 0.07 ms. `FakeFlip.run()` returns a `FlipOutcome`: the true row count 150,000 and a dictionary from the three experiment names to plan text, stale before the statistics are collected and indexed after the plain `ANALYZE` and after the extended statistics.

`tests/unit/application/fakes.py`, lines 151 to 164:

```python
class RecordingStore:
    def __init__(self) -> None:
        self.plans: dict[str, tuple[str, ...]] = {}
        self.texts: dict[str, str] = {}
        self.report: str | None = None

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        self.plans[name] = tuple(lines)

    def save_text(self, name: str, text: str) -> None:
        self.texts[name] = text

    def save_report(self, text: str) -> None:
        self.report = text
```

`RecordingStore` keeps what the replay saves: plans by name, free-form texts (the lock queue capture) by file name, and the report.

#### `tests/unit/application/test_scenarios.py`

`Scenarios` runs one experiment each: the lock queue, the forced conflict, the safe migration, the two index builds, the two ways to add NOT NULL and the plan flip. It takes its collaborators as arguments, including a `pause` function to wait, so the test can pass `pauses.append` and record the waits instead of waiting.

`tests/unit/application/test_scenarios.py`, lines 1 to 11:

```python
from locks_lab.application.scenarios import SETTLE_SECONDS, Scenarios

from .fakes import FakeChanges, FakeFlip, FakeLoad, FakeLocks, FakeTable, window


def build(**options):
    changes, locks, pauses = FakeChanges(), FakeLocks(), list[float]()
    scenarios = Scenarios(
        table=FakeTable(), locks=locks, changes=changes, flip=FakeFlip(), pause=pauses.append, **options
    )
    return scenarios, changes, locks, pauses
```

`SETTLE_SECONDS` is the short wait the scenarios take after a disruptive change so that the load can settle before the window is read. `build(**options)` creates the fakes and the `Scenarios`; `list[float]()` is another way to write an empty list of floats. It returns the pieces a test wants to inspect.

`tests/unit/application/test_scenarios.py`, lines 14 to 22:

```python
def test_the_lock_queue_reports_the_snapshot_the_pile_up_window_and_the_recovery():
    scenarios, _changes, locks, _pauses = build()
    load = FakeLoad([window(3000.0, errors=5, stalled=6), window(4.0)])
    result = scenarios.lock_queue(load, hold_seconds=4)
    assert locks.holds == [4]
    assert result.during.p99_ms == 3000.0
    assert result.after.p99_ms == 4.0
    assert load.measured == [3], "three seconds of load after the long read is released"
    assert result.snapshot.request_of(391) is not None
```

`FakeLoad` is given two scripted windows: first one with a p99 of 3000 ms, 5 errors and 6 stalled seconds (the pile-up behind the ALTER), then one with 4 ms (the recovery). After `scenarios.lock_queue(load, hold_seconds=4)`: the fake lock object was asked to hold 4 seconds, the window `during` is the first scripted one, `after` the second, and the load was asked to measure once, for `[3]` seconds (the message after the comma says why). The snapshot must contain the request of session 391.

`tests/unit/application/test_scenarios.py`, lines 25 to 29:

```python
def test_a_forced_conflict_waits_for_the_queue_it_joined_to_drain():
    scenarios, _changes, locks, pauses = build()
    assert scenarios.forced_conflict("1s").failed_fast
    assert locks.timeouts == ["1s"]
    assert pauses == [SETTLE_SECONDS]
```

A forced conflict makes a second session try for the lock with a short `lock_timeout` while the queue is still there. It must report that it failed fast, the timeout `1s` must have reached the lock object, and the scenario must wait `SETTLE_SECONDS` once afterwards, because the queue it joined must drain before the next experiment starts.

`tests/unit/application/test_scenarios.py`, lines 32 to 37:

```python
def test_the_safe_migration_adds_the_column_then_backfills_and_counts_what_is_left():
    scenarios, changes, _locks, _pauses = build()
    result = scenarios.safe_migration(FakeLoad([window(10.0)]), batch_size=2000, pause_seconds=0.05)
    assert changes.calls == ["add_flagged_column", "backfill 2000 0.05"]
    assert (result.batches, result.add_column_attempts, result.rows_still_null) == (100, 1, 0)
    assert result.summary.p99_ms == 10.0
```

The safe migration adds the column, then backfills in batches, then counts what is left. The recorded calls must be exactly `add_flagged_column` then `backfill 2000 0.05`. The result must show 100 batches, one attempt to add the column and no rows still NULL, and carry the window the load script produced, p99 10.0.

`tests/unit/application/test_scenarios.py`, lines 40 to 42:

```python
def test_a_stop_request_ends_the_backfill_without_error():
    scenarios, _changes, _locks, _pauses = build(should_stop=lambda: True)
    assert scenarios.safe_migration(FakeLoad(), 2000, 0.05).batches == 0
```

If a stop is requested, the backfill must end without an error and report 0 batches. `should_stop=lambda: True` is a function that always answers yes.

`tests/unit/application/test_scenarios.py`, lines 45 to 50:

```python
def test_the_plain_index_build_settles_before_the_window_is_read():
    scenarios, changes, _locks, pauses = build()
    result = scenarios.plain_index(FakeLoad([window(600.0, max_ms=600.0)]))
    assert changes.calls == ["plain_index_build"]
    assert (result.build_seconds, result.summary.max_ms) == (0.8, 600.0)
    assert pauses == [SETTLE_SECONDS]
```

The plain index build is read after the load has had time to settle: the recorded call is `plain_index_build`, the build took 0.8 seconds, the window's longest operation was 600 ms, and one pause of `SETTLE_SECONDS` was made before the window was read.

`tests/unit/application/test_scenarios.py`, lines 53 to 58:

```python
def test_the_concurrent_index_is_interrupted_then_rebuilt_under_load():
    scenarios, changes, _locks, _pauses = build()
    result = scenarios.concurrent_index(FakeLoad())
    assert changes.calls == ["interrupted_concurrent_build", "rebuild_invalid_index"]
    assert result.interrupted.invalid_indexes == ("idx_events_device_created",)
    assert result.valid_after_rebuild
```

The concurrent index scenario first starts a build and cancels it, which leaves an invalid index behind, and then rebuilds it. The calls are in that order, the interrupted build names `idx_events_device_created` as invalid, and the rebuilt index is valid.

`tests/unit/application/test_scenarios.py`, lines 61 to 67:

```python
def test_the_naive_and_the_safe_not_null_are_measured_separately():
    scenarios, changes, _locks, _pauses = build()
    naive = scenarios.naive_not_null(FakeLoad())
    safe = scenarios.safe_not_null(FakeLoad())
    assert changes.calls == ["naive_set_not_null", "not_null_in_three_moves"]
    assert naive.report.seconds > 100 * safe.steps["set_not_null"].seconds
    assert safe.steps["validate"].lock_modes == ("ShareUpdateExclusiveLock",)
```

The naive and the safe way to make the column NOT NULL are separate scenarios with separate measurements. The calls are `naive_set_not_null` then `not_null_in_three_moves`. The naive statement (0.18 seconds) took more than 100 times as long as the safe final move (0.0007 seconds), and the validation step holds only the `ShareUpdateExclusiveLock`, the lock that lets reads and writes continue.

`tests/unit/application/test_scenarios.py`, lines 70 to 78:

```python
def test_the_plan_flip_parses_the_three_plans():
    result = build()[0].plan_flip()
    assert result.actual_rows == 150_000
    assert result.plans["f1_stale_statistics"].scans_everything
    assert result.plans["f3_after_extended_statistics"].estimate == 150_000


def test_the_table_size_comes_from_the_table():
    assert build()[0].table_size().pretty == "194 MB"
```

`build()[0]` takes the first item of the returned tuple, the `Scenarios` object. `plan_flip()` must return the true row count 150,000, a stale plan that scans everything, and an extended-statistics plan whose estimate equals the true count. The last test reads the table size through the scenario and expects the text `194 MB`, the first size the fake table reports.

#### `tests/unit/application/test_replay.py`

`ReplayLesson` runs the whole lesson: it resets the table, measures a baseline, performs the six steps while recording marks in the load record, and finally a closing baseline, then saves the notes.

`tests/unit/application/test_replay.py`, lines 1 to 26:

```python
import pytest

from locks_lab.application.replay import ReplayLesson
from locks_lab.application.scenarios import Scenarios
from locks_lab.domain.errors import LessonInterruptedError
from locks_lab.domain.host import HostLoad

from .fakes import FakeChanges, FakeFlip, FakeLoad, FakeLocks, FakeTable, RecordingStore, window


def build(windows=None, **options):
    table, store, changes = FakeTable(), RecordingStore(), FakeChanges()
    load = FakeLoad(windows)
    scenarios = Scenarios(table=table, locks=FakeLocks(), changes=changes, flip=FakeFlip(), pause=lambda _s: None)
    replay = ReplayLesson(
        load=load,
        table=table,
        scenarios=scenarios,
        store=store,
        baseline_seconds=60,
        closing_seconds=20,
        batch_size=2000,
        pause_seconds=0.05,
        **options,
    )
    return replay, load, table, store, changes
```

Imports, then `build(windows=None, **options)` wires the fakes. `windows` scripts what the load will report; `**options` collects any other keyword arguments (such as `host_load` or `should_stop`) and passes them to `ReplayLesson`. `pause=lambda _s: None` is a pause that does not wait. The fixed values, 60 seconds of baseline, 20 of closing baseline, batches of 2000 and 0.05 seconds between batches, match the defaults. The function returns the replay and the fakes.

`tests/unit/application/test_replay.py`, lines 29 to 40:

```python
def test_the_steps_run_in_the_lessons_order():
    replay, _load, _table, _store, changes = build()
    replay.run()
    assert changes.calls == [
        "add_flagged_column",
        "backfill 2000 0.05",
        "plain_index_build",
        "interrupted_concurrent_build",
        "rebuild_invalid_index",
        "naive_set_not_null",
        "not_null_in_three_moves",
    ]
```

The recorded calls are the lesson in order: add the column, backfill, the plain index build, the interrupted concurrent build, the rebuild, the naive NOT NULL, and the three-move NOT NULL.

`tests/unit/application/test_replay.py`, lines 43 to 55:

```python
def test_every_step_is_marked_in_the_load_record():
    replay, load, *_ = build()
    replay.run()
    assert [mark.split(":")[0] for mark in load.marks] == [
        "reset to the seed's rows",
        "step 1",
        "step 2",
        "step 3",
        "step 4",
        "step 5",
        "step 6",
        "closing baseline",
    ]
```

The load record is marked at each step so the result can be read against time. `mark.split(":")[0]` keeps the text before the first colon. The marks are the reset, steps 1 to 6 and the closing baseline.

`tests/unit/application/test_replay.py`, lines 58 to 62:

```python
def test_the_baseline_and_the_closing_baseline_are_measured_at_the_configured_lengths():
    replay, load, *_ = build()
    replay.run()
    assert load.measured[0] == 60
    assert load.measured[-1] == 20
```

`load.measured` is the list of window lengths the replay asked for. The first is 60 seconds (the opening baseline) and the last is 20 (the closing baseline); `[-1]` is the last item of a list.

`tests/unit/application/test_replay.py`, lines 65 to 68:

```python
def test_the_table_is_reset_before_the_lesson_and_after_each_experiment_that_leaves_something():
    replay, _load, table, *_ = build()
    replay.run()
    assert table.resets == 4
```

The fake table counts resets. The replay resets once before the lesson and after each experiment that leaves something behind (the plain index, the interrupted build and the NOT NULL step), four in all.

`tests/unit/application/test_replay.py`, lines 71 to 77:

```python
def test_the_lock_queue_and_the_plans_are_saved_beside_the_notes():
    replay, _load, _table, store, _changes = build()
    result = replay.run()
    assert "naive-alter" in store.texts["lock_queue.txt"]
    assert set(store.plans) == {"f1_stale_statistics", "f2_after_analyze", "f3_after_extended_statistics"}
    assert store.report is not None
    assert result.rows == 2_000_000
```

The lock queue capture (a text file called `lock_queue.txt`, containing the application name `naive-alter`) and the three statistics plans are saved beside the notes, and the result carries the row count 2,000,000 from the fake table.

`tests/unit/application/test_replay.py`, lines 80 to 85:

```python
def test_the_bar_is_twice_the_higher_of_the_opening_and_closing_baselines():
    windows = [window(5.0)] + [window(1.0)] * 20 + [window(7.0)]
    replay, *_ = build(windows)
    result = replay.run()
    assert result.opening.p99_ms == 5.0
    assert result.bar.limit_ms == 2 * max(result.opening.p99_ms, result.closing.p99_ms)
```

The windows are scripted as a list: the first is the opening baseline with p99 5.0, then twenty windows of 1.0, then a closing one with 7.0. The bar must be twice the higher of the opening and closing baselines. `[window(1.0)] * 20` repeats an item twenty times; `+` joins lists.

`tests/unit/application/test_replay.py`, lines 88 to 92:

```python
def test_the_host_load_is_carried_into_the_notes():
    replay, _load, _table, store, _changes = build(host_load=HostLoad(40.0, 12))
    replay.run()
    assert store.report is not None
    assert "Measured on a loaded machine (load average 40.0 on 12 CPUs)" in store.report
```

A `HostLoad` of 40.0 on 12 CPUs is passed in and the notes must say the machine was loaded.

`tests/unit/application/test_replay.py`, lines 95 to 105:

```python
def test_a_stop_request_ends_the_replay_before_the_next_step_without_notes():
    calls = []

    def should_stop() -> bool:
        calls.append(1)
        return len(calls) > 3

    replay, _load, _table, store, _changes = build(should_stop=should_stop)
    with pytest.raises(LessonInterruptedError):
        replay.run()
    assert store.report is None
```

To test Ctrl-C without a real signal, `should_stop` is a function defined inside the test that counts how often it is asked and answers yes after the third time. The replay must raise `LessonInterruptedError` between steps and must not have saved any notes (`store.report is None`).

`tests/unit/application/test_replay.py`, lines 108 to 112:

```python
def test_progress_is_reported_for_each_step():
    messages: list[str] = []
    replay, *_ = build(progress=messages.append)
    replay.run()
    assert "step 5: NOT NULL" in messages
```

Progress messages are collected with `progress=messages.append`; the message for step 5 must be exactly `step 5: NOT NULL`.

#### `tests/unit/application/test_report.py`

`tests/unit/application/test_report.py`, lines 1 to 21:

```python
from locks_lab.application.replay import ReplayLesson
from locks_lab.application.report import render_results
from locks_lab.application.scenarios import Scenarios
from locks_lab.domain.host import HostLoad

from .fakes import FakeChanges, FakeFlip, FakeLoad, FakeLocks, FakeTable, RecordingStore, window


def result(**options):
    table = FakeTable()
    scenarios = Scenarios(table=table, locks=FakeLocks(), changes=FakeChanges(), flip=FakeFlip(), pause=lambda _s: None)
    return ReplayLesson(
        load=FakeLoad(options.pop("windows", None)),
        table=table,
        scenarios=scenarios,
        store=RecordingStore(),
        baseline_seconds=60,
        batch_size=2000,
        pause_seconds=0.05,
        **options,
    ).run()
```

`result(**options)` runs a whole fake replay and returns its result. `options.pop("windows", None)` removes the `windows` key from the options (or gives `None` if it is not there) so that the rest can be passed on to `ReplayLesson`.

`tests/unit/application/test_report.py`, lines 24 to 28:

```python
def test_the_windows_table_has_a_row_per_step_with_the_verdict():
    text = render_results(result())
    assert "| 1 baseline, opening |" in text
    assert "| 2 naive ALTER behind a long read (6 s) |" in text
    assert "| 5 NOT NULL in three moves |" in text
```

The windows table has one row per step, each beginning with the step's number and name; the test checks three of them.

`tests/unit/application/test_report.py`, lines 31 to 35:

```python
def test_a_window_within_the_bar_is_marked_yes_and_one_without_is_marked_no():
    windows = [window(5.0)] + [window(100.0, errors=3)] + [window(5.0)] * 20
    text = render_results(result(windows=windows))
    assert any(line.startswith("| 2 naive") and line.endswith("| no |") for line in text.splitlines())
    assert any(line.startswith("| 1 baseline, opening") and line.endswith("| yes |") for line in text.splitlines())
```

Each row ends with a verdict column, `yes` if the window stayed within the bar and `no` otherwise. The scripted windows are: opening 5.0, then the window of step 2 with p99 100.0 and 3 errors, then twenty at 5.0. The row for step 2 must end with `| no |` and the opening row with `| yes |`. `text.splitlines()` cuts the text into lines and `any(...)` over a generator expression is true if at least one line matches.

`tests/unit/application/test_report.py`, lines 38 to 42:

```python
def test_the_lock_queue_the_bloat_and_the_not_null_table_are_in_the_notes():
    text = render_results(result())
    assert "waited 6.0 s for a read-only transaction" in text
    assert "table 194 MB before, 357 MB after the backfill (1,368,325 dead row versions)" in text
    assert "| validate | `VALIDATE CONSTRAINT` | ShareUpdateExclusiveLock | 140.0 |" in text
```

Three pieces of the notes: the sentence about the lock queue (`waited 6.0 s for a read-only transaction`), the table-bloat sentence built from the two sizes of the fake table (194 MB before the backfill, 357 MB after, with 1,368,325 dead row versions, the old copies of rows that the backfill's updates leave behind until a vacuum removes them), and the row of the NOT NULL table for the validation step with its lock mode and 140.0 ms.

`tests/unit/application/test_report.py`, lines 45 to 47:

```python
def test_the_plan_flip_table_shows_the_estimate_against_the_actual_rows():
    text = render_results(result())
    assert "| Before statistics catch up | 1 (filtered scan node) | 150,000 | Sort / Seq Scan | 175.0 |" in text
```

The plan flip table compares the planner's estimate with the real number of rows: for the stale plan the estimate is 1 (with the note `filtered scan node`), the actual is 150,000, the nodes are `Sort / Seq Scan` and the time is 175.0 ms.

`tests/unit/application/test_report.py`, lines 50 to 53:

```python
def test_a_quiet_machine_gets_the_plain_load_line_and_a_loaded_one_the_warning():
    assert "Measured at load average 2.0 on 12 CPUs." in render_results(result(host_load=HostLoad(2.0, 12)))
    assert "rerun `make run` on a quiet machine" in render_results(result(host_load=HostLoad(40.0, 12)))
    assert "Measured" not in render_results(result())
```

A quiet machine (load 2.0 on 12 CPUs) gets the plain sentence, a loaded one (40.0) gets the advice to rerun on a quiet machine, and without a load the word `Measured` appears nowhere.

#### `tests/unit/infrastructure/test_settings.py`

`Settings.from_env` reads configuration from a dictionary of environment variables, the named text values a program receives from the shell that starts it. Tests pass a dictionary instead of the real environment, which makes them independent of the machine.

`tests/unit/infrastructure/test_settings.py`, lines 1 to 5:

```python
import pytest

from locks_lab.infrastructure.settings import ConfigurationError, Settings

MINIMAL = {"PGPASSWORD": "s3cret-value"}
```

`MINIMAL` is the one variable that has no default: the database password, set to a harmless made-up value.

`tests/unit/infrastructure/test_settings.py`, lines 8 to 23:

```python
def test_defaults_describe_the_local_compose_setup():
    settings = Settings.from_env(MINIMAL)
    postgres = settings.postgres
    assert (postgres.host, postgres.port, postgres.database, postgres.user) == ("localhost", 55433, "lab", "lab")
    assert (settings.load.iterations_per_second, settings.load.workers, settings.load.statement_timeout_ms) == (
        40,
        4,
        3000,
    )
    assert (settings.migration.batch_size, settings.migration.pause_seconds, settings.migration.lock_timeout) == (
        2000,
        0.05,
        "2s",
    )
    assert (settings.baseline_seconds, settings.closing_seconds, settings.log_level) == (60, 20, "INFO")
    assert settings.sql_dir.name == "sql"
```

With only the password, every other setting takes its default. The database is on `localhost` port `55433` (the lab's port, so that it does not clash with the other labs or with a PostgreSQL on 5432), database and user `lab`. The load: 40 iterations a second, 4 workers (threads), and a statement timeout of 3000 ms. The migration: batches of 2000 rows, a pause of 0.05 seconds between batches, and a `lock_timeout` of `2s`. The windows: a baseline of 60 seconds, a closing baseline of 20, log level `INFO`, and the SQL folder is named `sql`. The two long assertions are written with the tuple split over several lines because the formatter lays out the tuple of three expected values one per line when it does not fit.

`tests/unit/infrastructure/test_settings.py`, lines 26 to 28:

```python
def test_the_database_password_has_no_default():
    with pytest.raises(ConfigurationError, match="PGPASSWORD"):
        Settings.from_env({})
```

No variables at all: a `ConfigurationError` that names `PGPASSWORD`.

`tests/unit/infrastructure/test_settings.py`, lines 31 to 32:

```python
def test_the_password_never_appears_in_a_printed_settings_object():
    assert "s3cret-value" not in repr(Settings.from_env(MINIMAL))
```

The printed form of the settings object (`repr`) must not contain the password.

`tests/unit/infrastructure/test_settings.py`, lines 35 to 60:

```python
def test_every_variable_can_be_overridden():
    settings = Settings.from_env(
        {
            **MINIMAL,
            "PGHOST": "db",
            "PGPORT": "6543",
            "PGDATABASE": "x",
            "PGUSER": "u",
            "LOAD_ITERATIONS_PER_SECOND": "10",
            "LOAD_WORKERS": "2",
            "LOAD_STATEMENT_TIMEOUT_MS": "500",
            "BACKFILL_BATCH": "10000",
            "BACKFILL_PAUSE_SECONDS": "0.1",
            "LOCK_TIMEOUT": "500ms",
            "BASELINE_SECONDS": "600",
            "CLOSING_SECONDS": "30",
            "LAB_SQL_DIR": "/somewhere/sql",
            "LOG_LEVEL": "debug",
        }
    )
    assert (settings.postgres.host, settings.postgres.port) == ("db", 6543)
    assert (settings.load.iterations_per_second, settings.load.workers) == (10, 2)
    assert (settings.migration.batch_size, settings.migration.pause_seconds) == (10000, 0.1)
    assert settings.migration.lock_timeout == "500ms"
    assert (settings.baseline_seconds, settings.closing_seconds) == (600, 30)
    assert (settings.log_level, str(settings.sql_dir)) == ("DEBUG", "/somewhere/sql")
```

Every variable can be overridden. All the values are text; the settings code converts them. The checks compare tuples of fields: host `db` and port 6543, ten iterations a second with two workers, a batch of 10,000 with a pause of 0.1 seconds, a lock timeout of `500ms` (kept as text because it is passed to PostgreSQL as is), a 600 second baseline and a 30 second closing window, the log level in upper case (`debug` becomes `DEBUG`), and the SQL folder.

`tests/unit/infrastructure/test_settings.py`, lines 63 to 78:

```python
@pytest.mark.parametrize(
    "extra",
    [
        {"PGPORT": "0"},
        {"PGHOST": "  "},
        {"LOAD_WORKERS": "0"},
        {"BACKFILL_BATCH": "many"},
        {"BACKFILL_PAUSE_SECONDS": "-1"},
        {"BACKFILL_PAUSE_SECONDS": "soon"},
        {"LOCK_TIMEOUT": "2 seconds"},
        {"LOG_LEVEL": "LOUD"},
    ],
)
def test_an_unusable_value_is_rejected_with_the_variable_name(extra):
    with pytest.raises(ConfigurationError, match=next(iter(extra))):
        Settings.from_env({**MINIMAL, **extra})
```

This parametrized test runs once for each bad input: port 0, a host of only spaces, zero workers, a batch size that is a word, a negative pause, a pause that is a word, a lock timeout in a form PostgreSQL would not accept (`2 seconds` has a space), and an unknown log level. Each time the settings must raise `ConfigurationError` and the message must contain the variable's name; `next(iter(extra))` takes the one key of the one-item dictionary and uses it as the pattern.

`tests/unit/infrastructure/test_settings.py`, lines 81 to 83:

```python
def test_settings_read_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "from-the-process")
    assert Settings.from_env().postgres.password == "from-the-process"
```

With no argument `from_env` reads the real process environment; `monkeypatch.setenv` sets a variable for this test only.

#### `tests/unit/interfaces/test_cli.py`

The three command-line programs (`health_cli`, `run_cli`, `load_cli`) return an integer exit code: 0 for success, 1 for a lab failure, 2 for a configuration problem and 130 for an interrupted run (128 plus 2, the number of `SIGINT`, the signal Ctrl-C sends). The tests call each program's `main` with a list of arguments instead of starting a new process.

`tests/unit/interfaces/test_cli.py`, lines 1 to 5:

```python
import pytest

from locks_lab.application.health import ProbeFailedError
from locks_lab.domain.errors import LabError
from locks_lab.interfaces import health_cli, load_cli, run_cli
```

The imports include `LabError`, the base class of the lab's own errors, and the three program modules.

`tests/unit/interfaces/test_cli.py`, lines 8 to 13:

```python
def test_a_missing_password_is_a_configuration_error_with_exit_code_2_for_every_program(monkeypatch, capsys):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    assert health_cli.main([]) == 2
    assert run_cli.main([]) == 2
    assert load_cli.main([]) == 2
    assert "PGPASSWORD" in capsys.readouterr().err
```

With the password removed (`raising=False` means "no complaint if it was not set") every program returns 2 and the standard error text, read with `capsys.readouterr().err`, names `PGPASSWORD`.

`tests/unit/interfaces/test_cli.py`, lines 16 to 28:

```python
class FailingProbe:
    name = "postgres"

    def __init__(self, _settings) -> None:
        pass

    def check(self) -> str:
        raise ProbeFailedError("the events table is empty or not seeded; run make db")


class PassingProbe(FailingProbe):
    def check(self) -> str:
        return "2,000,000 events"
```

`FailingProbe` stands in for the health probe: it takes the settings in its constructor and ignores them, has the name `postgres`, and its `check` raises `ProbeFailedError` with a reason. `PassingProbe(FailingProbe)` is a **subclass**: it inherits everything and overrides only `check`, so that it returns `2,000,000 events`.

`tests/unit/interfaces/test_cli.py`, lines 31 to 42:

```python
def test_health_is_exit_1_when_the_probe_fails(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setattr(health_cli, "PostgresEventsProbe", FailingProbe)
    assert health_cli.main([]) == 1
    assert "FAIL postgres: the events table is empty" in capsys.readouterr().out


def test_health_is_exit_0_when_the_probe_passes(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setattr(health_cli, "PostgresEventsProbe", PassingProbe)
    assert health_cli.main([]) == 0
    assert "ok postgres: 2,000,000 events" in capsys.readouterr().out
```

`monkeypatch.setattr(health_cli, "PostgresEventsProbe", FailingProbe)` replaces the real probe class inside the `health_cli` module for this test. With the failing probe the program returns 1 and prints a line beginning `FAIL postgres:` followed by the reason; with the passing probe it returns 0 and prints `ok postgres: 2,000,000 events`.

`tests/unit/interfaces/test_cli.py`, lines 45 to 67:

```python
class FakeReplay:
    """Stands in for ReplayLesson: returns what the test says, or raises what it says."""

    outcome: object = None

    def __init__(self, **_options) -> None:
        pass

    def run(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeLoadContext:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None
```

`FakeReplay` stands in for `ReplayLesson`. Its class attribute `outcome` is set by each test. The constructor accepts any keyword arguments (`**_options`) and ignores them. `run()` raises the outcome if it is an exception (`isinstance(self.outcome, Exception)`) and returns it otherwise. `FakeLoadContext` replaces `ThreadedLoad`, which is used in a `with` block: `__enter__` and `__exit__` are the two methods that make an object usable in a `with` statement, and here they do nothing (`__exit__` returning `None` means errors are not swallowed).

`tests/unit/interfaces/test_cli.py`, lines 70 to 76:

```python
def patch_run(monkeypatch, outcome):
    monkeypatch.setenv("PGPASSWORD", "x")
    FakeReplay.outcome = outcome
    monkeypatch.setattr(run_cli, "ReplayLesson", FakeReplay)
    monkeypatch.setattr(run_cli, "ThreadedLoad", FakeLoadContext)
    monkeypatch.setattr(run_cli, "build_table", lambda _settings: None)
    monkeypatch.setattr(run_cli, "build_scenarios", lambda *_args: None)
```

`patch_run(monkeypatch, outcome)` prepares a `run_cli` that touches no database: it sets a password, stores the outcome on `FakeReplay`, and replaces `ReplayLesson`, `ThreadedLoad`, `build_table` and `build_scenarios` in the `run_cli` module. The `lambda *_args:` forms accept any arguments and return nothing.

`tests/unit/interfaces/test_cli.py`, lines 79 to 88:

```python
def test_an_interrupted_replay_exits_with_130(monkeypatch, tmp_path):
    from locks_lab.domain.errors import LessonInterruptedError

    patch_run(monkeypatch, LessonInterruptedError("stopped"))
    assert run_cli.main(["--output-dir", str(tmp_path)]) == 130


def test_a_lab_error_exits_with_1(monkeypatch, tmp_path):
    patch_run(monkeypatch, LabError("boom"))
    assert run_cli.main(["--output-dir", str(tmp_path)]) == 1
```

An interrupted replay (the fake raises `LessonInterruptedError`) makes the program exit with 130. An ordinary lab error (`LabError("boom")`) makes it exit with 1. `--output-dir` points at the temporary folder `tmp_path`, created fresh for each test.

`tests/unit/interfaces/test_cli.py`, lines 91 to 101:

```python
def test_a_finished_replay_prints_whether_the_safe_migration_met_the_bar(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    from locks_lab.domain.stats import Bar

    from ..application.fakes import window

    outcome = SimpleNamespace(bar=Bar(10.0), safe=SimpleNamespace(summary=window(12.0)))
    patch_run(monkeypatch, outcome)
    assert run_cli.main(["--output-dir", str(tmp_path), "--baseline-seconds", "5"]) == 0
    assert "safe migration p99 12.0 ms: within twice the baseline (10.0 ms)" in capsys.readouterr().out
```

A finished replay prints whether the safe migration met the bar. `types.SimpleNamespace` builds a plain object with attributes, enough to stand in for the replay's result: a bar of 10.0 ms and a safe migration summary with p99 12.0 ms. The program is run with `--baseline-seconds 5` and must return 0 and print `safe migration p99 12.0 ms: within twice the baseline (10.0 ms)`. 12.0 is below the limit of 20.0, which is twice the baseline.

`tests/unit/interfaces/test_cli.py`, lines 104 to 106:

```python
def test_a_bad_argument_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        run_cli.main(["--baseline-seconds", "x"])
```

An argument the parser cannot read (`x` where a number is expected) makes `argparse`, Python's command-line parser, print a usage message and raise `SystemExit`.

#### `tests/unit/infrastructure/test_sql_script.py`

PostgreSQL's driver can run only one statement at a time, but the lab's `.sql` files hold several. `split_statements` cuts a script into single statements. It must not cut at a semicolon inside a comment, inside quotes or inside a **dollar-quoted** block (text between `$$` and `$$`, or between `$tag$` and `$tag$`, which PostgreSQL treats as one string), and it must drop lines that belong to the `psql` program rather than to SQL (lines starting with a backslash).

`tests/unit/infrastructure/test_sql_script.py`, lines 1 to 7:

```python
import pathlib

from locks_lab.infrastructure.sql_script import split_statements


def test_statements_are_split_on_semicolons():
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]
```

`pathlib` is used by the last test. The first test: two statements separated by semicolons come back as two strings without their semicolons.

`tests/unit/infrastructure/test_sql_script.py`, lines 10 to 11:

```python
def test_comments_are_dropped_even_with_a_semicolon_in_them():
    assert split_statements("-- one; two\nSELECT 1; -- trailing; note\nSELECT 2;") == ["SELECT 1", "SELECT 2"]
```

SQL comments start with two hyphens and run to the end of the line. Two of them contain semicolons; none may split anything, and none may appear in the result. In the Python string `\n` is a line break.

`tests/unit/infrastructure/test_sql_script.py`, lines 14 to 15:

```python
def test_a_semicolon_inside_quotes_does_not_split():
    assert split_statements("SELECT 'a;b'; SELECT \"c;d\";") == ["SELECT 'a;b'", 'SELECT "c;d"']
```

A semicolon inside single quotes (a text value) or double quotes (an identifier) is part of the text. The Python string uses `\"` for a double quote inside a double-quoted string; the expected list uses single quotes around the second item for the same reason.

`tests/unit/infrastructure/test_sql_script.py`, lines 18 to 23:

```python
def test_a_do_block_is_one_statement_whatever_it_contains():
    sql = "DO $$\nBEGIN\n  IF true THEN SELECT 1; END IF;\nEND\n$$;\nSELECT 2;"
    statements = split_statements(sql)
    assert len(statements) == 2
    assert statements[0].startswith("DO $$")
    assert statements[0].endswith("$$")
```

A `DO` block is a piece of procedural code that PostgreSQL runs once, written between `$$` marks. It contains semicolons inside, so it must stay one statement. The script has the block and then `SELECT 2;`, so there are two statements; the first starts with `DO $$` and ends with the closing `$$`.

`tests/unit/infrastructure/test_sql_script.py`, lines 26 to 27:

```python
def test_a_tagged_dollar_quote_is_one_statement():
    assert split_statements("SELECT $q$a;b$q$; SELECT 2;") == ["SELECT $q$a;b$q$", "SELECT 2"]
```

A dollar quote can carry a tag, here `$q$`, and the semicolon inside it (`a;b`) does not split.

`tests/unit/infrastructure/test_sql_script.py`, lines 30 to 31:

```python
def test_psql_meta_commands_are_not_sql():
    assert split_statements("\\set rows 5\nSELECT 1;\n\\gset\n") == ["SELECT 1"]
```

Lines like `\set rows 5` and `\gset` are commands of the `psql` program, not SQL; the server would answer with a syntax error. They must vanish. In Python source `"\\set"` is how a single backslash is written.

`tests/unit/infrastructure/test_sql_script.py`, lines 34 to 41:

```python
def test_every_repository_sql_file_that_python_runs_splits_into_complete_statements():
    sql = pathlib.Path(__file__).resolve().parents[3] / "sql"
    files = [*sorted((sql / "migrations").rglob("*.sql")), *sorted((sql / "explain").glob("*.sql"))]
    files += [sql / "experiments" / "01_bulk_load_correlated_month.sql"]
    for path in files:
        statements = split_statements(path.read_text())
        assert statements, path.name
        assert all(not statement.endswith(";") for statement in statements)
```

The last test runs the splitter on the repository's real files. `pathlib.Path(__file__).resolve().parents[3] / "sql"` finds the `sql` folder: `__file__` is this test file, `.resolve()` makes the path absolute, `.parents[3]` goes up four levels (`infrastructure`, `unit`, `tests`, then the repository root; the count starts at zero for the immediate parent), and `/ "sql"` appends a folder name. The list `files` holds every file under `sql/migrations` (searched recursively with `rglob`) and every file in `sql/explain`, sorted so that failures are reproducible, plus the experiment script that bulk-loads a month of correlated data; `[*a, *b]` joins two sequences into one list. For each file, `assert statements, path.name` demands at least one statement and gives the file name as the failure message, and `all(...)` checks that no statement still ends with a semicolon.

#### `tests/unit/infrastructure/test_artifacts.py`

`FileArtifactStore` writes what the replay produces into a folder: plans, free-text captures and the results notes.

`tests/unit/infrastructure/test_artifacts.py`, lines 1 to 17:

```python
from locks_lab.infrastructure.artifacts import FileArtifactStore


def test_a_plan_is_written_as_name_dot_txt(tmp_path):
    store = FileArtifactStore(tmp_path / "out")
    store.save_plan("f1_stale_statistics", ["Seq Scan on events", "Execution Time: 1.0 ms"])
    assert (tmp_path / "out" / "f1_stale_statistics.txt").read_text() == "Seq Scan on events\nExecution Time: 1.0 ms\n"


def test_a_text_capture_keeps_its_own_name(tmp_path):
    FileArtifactStore(tmp_path).save_text("lock_queue.txt", "queue\n")
    assert (tmp_path / "lock_queue.txt").read_text() == "queue\n"


def test_the_report_is_written_as_results_md(tmp_path):
    FileArtifactStore(tmp_path).save_report("# Results\n")
    assert (tmp_path / "results.md").read_text() == "# Results\n"
```

`tmp_path` is a fresh empty folder that pytest creates for each test and removes afterwards. The `/` between a path and a text joins path parts, so `tmp_path / "out"` is a folder called `out` inside the temporary folder (which the store must create, because it does not exist yet). The first test saves a plan under the name `f1_stale_statistics` and requires a file `f1_stale_statistics.txt` holding the two lines joined by line breaks with a final line break (`read_text()` reads the whole file). The second test saves a text capture whose name already includes its extension, `lock_queue.txt`, and expects that exact file name. The third saves the report and expects `results.md` with exactly the given text.

#### `tests/integration/conftest.py`, the remaining lines

`tests/integration/conftest.py`, lines 1 to 1:

```python
"""Fixtures for the tests that need the seeded database from `make up db`, with the load script running."""
```

The module docstring says these fixtures need the seeded database and the running load script.

`tests/integration/conftest.py`, lines 10 to 17:

```python
from locks_lab.application.scenarios import Scenarios
from locks_lab.domain.stats import WindowSummary
from locks_lab.infrastructure import postgres
from locks_lab.infrastructure.lab_table import PostgresLabTable
from locks_lab.infrastructure.load_runner import ThreadedLoad
from locks_lab.infrastructure.lock_experiments import PostgresLockExperiments
from locks_lab.infrastructure.plan_flip import PostgresPlanFlip
from locks_lab.infrastructure.schema_changes import PostgresSchemaChanges
```

The imports bring in the scenarios, the summary type, the connection helper, and one adapter for each thing the lab does to the database: the table (reset), the load runner (it runs the load script in background threads), the lock experiments, the plan flip and the schema changes.

#### `tests/integration/test_lesson_outcomes.py`

One test per "Done when" line of the lesson, against the seeded database with the load running (`make up db` first). The marker `integration` is set for the whole file by `pytestmark`; `make test` runs only `tests/unit`, and `make test-integration` includes this file.

`tests/integration/test_lesson_outcomes.py`, lines 1 to 18:

```python
"""One test per "Done when" line of the lesson, against the seeded database with the load running (make up db first)."""

import pathlib
import threading
import time

import psycopg
import pytest

from locks_lab.domain.flip import parse_flip_plan
from locks_lab.domain.stats import Bar
from locks_lab.infrastructure.sql_script import run_file

from .conftest import bracket

pytestmark = pytest.mark.integration

SQL = pathlib.Path(__file__).resolve().parents[2] / "sql"
```

The imports: `pathlib`, `threading` (to release a long read after a delay), `time`, `psycopg` (the PostgreSQL driver), `pytest`, the plan parser, the `Bar` type, the helper that runs an SQL file, and `bracket` from `conftest.py`. `SQL` is the path to the repository's `sql` folder.

`tests/integration/test_lesson_outcomes.py`, lines 21 to 26:

```python
def test_step1_the_load_holds_a_steady_rate_with_stable_p99(load):
    windows = [load.measure(4) for _ in range(3)]
    assert all(w.errors == 0 and w.stalled_seconds == 0 for w in windows)
    assert all(w.ops_per_second >= 0.8 * 120 for w in windows), "the rate holds near 120 operations a second"
    p99s = sorted(w.p99_ms for w in windows)
    assert p99s[-1] <= 5 * max(p99s[1], 1.0), "no window's p99 is out of line with the others"
```

Step 1. `load` is a fixture that runs the load script in background threads for the whole test. The test measures three windows of 4 seconds each (`load.measure(4)` blocks for 4 seconds and returns a summary). In every window there must be no errors and no stalled second, the rate must be at least 80 percent of the configured 120 operations a second, and the p99 of the worst window must be no more than five times the middle one: `sorted(...)` puts the three p99s in order and `p99s[1]` is the middle value (`max(..., 1.0)` avoids comparing with zero). That is the proof that the load is steady enough to measure a migration against.

`tests/integration/test_lesson_outcomes.py`, lines 29 to 48:

```python
def test_step2_the_alter_waits_behind_a_long_read_and_the_load_waits_behind_the_alter(load, scenarios):
    result = scenarios.lock_queue(load, hold_seconds=4)
    snapshot = result.snapshot
    reader = next(request for request in snapshot.queue if request.application == "long-transaction")
    alter = snapshot.waiting_application("naive-alter")[0]
    assert reader.granted
    assert reader.mode == "AccessShareLock"
    assert alter.blocked_by == (reader.pid,), "the ALTER waits for the read-only transaction"
    alter_request = snapshot.request_of(alter.pid)
    assert alter_request is not None
    assert (alter_request.mode, alter_request.granted) == ("AccessExclusiveLock", False), "it never held its lock"
    behind_alter = snapshot.waiting_application("load")
    assert behind_alter
    assert all(session.blocked_by == (alter.pid,) for session in behind_alter), (
        "every load query waits for the ALTER, not for the read it has nothing to do with"
    )
    assert result.alter_seconds >= 3.5, "the ALTER did not run until the read ended"
    assert result.during.stalled_seconds >= 2
    assert result.during.ops_per_second < 12
    assert result.during.p99_ms >= 1000
```

Step 2 reproduces the lock queue. `scenarios.lock_queue(load, hold_seconds=4)` opens a long read-only transaction, then starts an `ALTER TABLE` that needs an exclusive lock, and takes a snapshot of the lock queue. The snapshot is examined: the reader (`next(...)` returns the first request whose application name is `long-transaction`) has been granted an `AccessShareLock`; the `naive-alter` session is blocked by exactly the reader's pid (`blocked_by == (reader.pid,)`, a one-item tuple); its own lock request is an `AccessExclusiveLock` that was never granted; and every load session that is waiting is blocked by the ALTER, not by the reader, which is the lesson: a request for an exclusive lock makes everything behind it wait. The window `during` shows the damage: the ALTER took at least 3.5 seconds (it did not run until the read ended), at least 2 seconds were stalled, the operation rate fell below 12 a second, and the p99 was at least a second. The text after each comma is shown if the assertion fails.

`tests/integration/test_lesson_outcomes.py`, lines 51 to 77:

```python
def test_step3_the_safe_migration_keeps_p99_within_twice_baseline_and_a_forced_conflict_fails_fast(
    load, scenarios, connection, settings
):
    def relfilenode() -> int:
        return int(connection.execute("SELECT relfilenode FROM pg_class WHERE oid = 'events'::regclass").fetchone()[0])

    before_file = relfilenode()

    def migrate_safely():
        conflict = scenarios.forced_conflict("1s")
        return conflict, scenarios.safe_migration(load, settings.migration.batch_size, settings.migration.pause_seconds)

    before, (conflict, safe), after = bracket(load, migrate_safely)
    bar = Bar.bracketing(before, after)
    assert conflict.failed_fast
    assert 0.9 <= conflict.seconds < 2.5, "it gave up at lock_timeout instead of queueing"
    assert relfilenode() == before_file, "adding the column rewrote nothing"
    assert safe.summary.errors == 0
    assert safe.summary.stalled_seconds == 0
    assert safe.summary.p99_ms <= bar.limit_ms, f"p99 {safe.summary.p99_ms} ms against a bar of {bar.limit_ms} ms"
    assert safe.rows_still_null == 0
    assert safe.batches >= 50
    default = connection.execute(
        "SELECT column_default FROM information_schema.columns WHERE table_name = 'events' AND column_name = 'flagged'"
    ).fetchone()
    assert default is not None
    assert default[0] == "false", "rows inserted during the migration got a value from the default"
```

Step 3. `connection` is a plain connection to the database. The inner function `relfilenode()` reads the number of the file that holds the table (`'events'::regclass` converts the name to PostgreSQL's internal object id) from `pg_class`; if the table were rewritten the number would change. The inner function `migrate_safely()` first runs the forced conflict with a lock timeout of 1 second and then the safe migration. `bracket(load, migrate_safely)` measures a baseline for 8 seconds, runs the function, and measures another baseline; it returns the three results as a tuple that the test unpacks into `before`, `(conflict, safe)` and `after`. `Bar.bracketing(before, after)` builds the pass mark from the higher baseline. The assertions: the forced conflict failed fast and gave up after about one second (between 0.9 and 2.5), not after waiting in the queue; the file number is unchanged, so adding the column rewrote nothing; the load had no errors and no stalled second; the p99 stayed within the bar; no rows are left without a value; the backfill ran at least 50 batches; and the column's default is the text `false`, read from `information_schema.columns`, so rows inserted while the migration ran got a value.

`tests/integration/test_lesson_outcomes.py`, lines 80 to 92:

```python
def test_step3_a_failed_attempt_retries_instead_of_giving_up(changes, settings):
    from locks_lab.infrastructure.postgres import connect

    long_read = connect(settings.postgres, autocommit=False, application_name="long-transaction")
    long_read.execute("SELECT * FROM events WHERE id = 1").fetchall()
    release = threading.Timer(3.0, long_read.rollback)  # after the first attempt's 2 s lock_timeout
    release.start()
    try:
        attempts = changes.apply(1)
    finally:
        release.join()
        long_read.close()
    assert attempts >= 2, "the first try hit lock_timeout; a retry after the read ended succeeded"
```

A failed attempt must be retried, not abandoned. The test opens a second connection named `long-transaction` with `autocommit=False` (so that its read stays in an open transaction) and reads a row, which takes a lock on the table. `threading.Timer(3.0, long_read.rollback)` runs the function `rollback` in another thread after 3 seconds; the comment says the delay is chosen to be after the first attempt's 2 second lock timeout. `changes.apply(1)` runs migration 1, which retries. In `finally` the timer is joined and the connection closed, whatever happens. `attempts >= 2` shows that the first try hit the lock timeout and a later try succeeded.

`tests/integration/test_lesson_outcomes.py`, lines 95 to 103:

```python
def test_step4_a_plain_index_build_stalls_writes_and_a_concurrent_one_does_not(load, scenarios):
    plain = scenarios.plain_index(load)
    time.sleep(2)
    concurrent = scenarios.concurrent_index(load)
    assert plain.summary.max_ms >= 0.5 * plain.build_seconds * 1000, "inserts waited for the whole build"
    assert concurrent.summary.errors == 0
    # Compared with the build's own length, not with the plain build: a loaded machine slows both builds, and the
    # question is whether any insert waited for the build.
    assert concurrent.summary.max_ms < 0.5 * concurrent.build_seconds * 1000, "writes kept flowing during the build"
```

Step 4. The plain index build blocks writes for its whole length; the concurrent one does not. `scenarios.plain_index(load)` builds a normal index while the load runs; `time.sleep(2)` lets the load recover; `scenarios.concurrent_index(load)` does the same with `CREATE INDEX CONCURRENTLY`. The slowest insert during the plain build must be at least half the build time, so inserts waited for the build. The concurrent window must have no errors and its slowest operation must be less than half of its own build time. The comment explains the choice: the test compares with the build's own length and not with the plain build, because a loaded machine slows both builds, and the point is whether any insert waited for the build.

`tests/integration/test_lesson_outcomes.py`, lines 106 to 114:

```python
def test_step4_an_interrupted_concurrent_build_leaves_an_invalid_index_that_is_found_and_dropped(changes, connection):
    interrupted = changes.interrupted_concurrent_build()
    assert interrupted.cancelled
    assert interrupted.invalid_indexes == ("idx_events_device_created",)
    assert interrupted.ready_but_invalid, "it is maintained on every write but no query can use it"
    assert connection.execute("SELECT pg_relation_size('idx_events_device_created')").fetchone()[0] > 0
    rebuilt = changes.rebuild_invalid_index()
    assert rebuilt.valid
    assert changes.invalid_indexes() == []
```

A concurrent build that is cancelled leaves an **invalid index**: it exists, it is kept up to date on every write, but no query can use it. `changes.interrupted_concurrent_build()` starts a build and cancels it. The result says it was cancelled, names exactly `idx_events_device_created` as invalid, and says the index is ready but invalid. `pg_relation_size` shows that the index occupies disk space. `rebuild_invalid_index()` drops and rebuilds it, and afterwards it is valid and the list of invalid indexes is empty.

`tests/integration/test_lesson_outcomes.py`, lines 117 to 135:

```python
def test_step5_not_null_in_three_moves_holds_each_lock_only_briefly(settings, changes, scenarios):
    from locks_lab.infrastructure.load_runner import ThreadedLoad

    changes.add_flagged_column()
    changes.backfill_flagged(500_000, 0, lambda: False)  # no load yet: just prepare the column
    with ThreadedLoad(settings.postgres, settings.load) as running:
        running.measure(3)
        naive = scenarios.naive_not_null(running)
        safe = scenarios.safe_not_null(running)
    moves = safe.steps
    assert moves["add_check_not_valid"].lock_modes == ("AccessExclusiveLock",)
    assert moves["add_check_not_valid"].seconds < 0.5
    assert moves["validate"].lock_modes == ("ShareUpdateExclusiveLock",), "reads and writes continue during the scan"
    assert moves["set_not_null"].lock_modes == ("AccessExclusiveLock",)
    assert moves["set_not_null"].seconds < 0.5
    assert naive.report.seconds > 5 * moves["set_not_null"].seconds, "without the validated CHECK it scans the table"
    assert safe.summary.errors == 0
    assert safe.summary.stalled_seconds == 0
    assert safe.summary.max_ms < 500
```

Step 5. The column is prepared and given values (`backfill_flagged(500_000, 0, lambda: False)` updates up to 500,000 rows in one batch, with no pause, and the stop callback always answers no). `with ThreadedLoad(...) as running:` starts a fresh load for the block. After a 3 second warm-up the naive way (`SET NOT NULL` directly, which scans the table under an exclusive lock) and the safe way in three moves are run. The safe `steps` dictionary is checked: adding the constraint as `NOT VALID` takes an `AccessExclusiveLock` for under half a second; validating takes only the `ShareUpdateExclusiveLock`, so that reads and writes continue; and the final `SET NOT NULL` takes an exclusive lock for under half a second because PostgreSQL skips the scan when a validated constraint already proves the column has no nulls. The naive statement took more than five times as long as that final move. The load had no errors and no stalls and its slowest operation stayed under 500 ms.

`tests/integration/test_lesson_outcomes.py`, lines 138 to 148:

```python
def test_step5_the_column_ends_not_null_and_the_helper_constraint_is_gone(settings, changes, connection):
    changes.add_flagged_column()
    changes.backfill_flagged(500_000, 0, lambda: False)
    changes.not_null_in_three_moves()
    assert connection.execute(
        "SELECT attnotnull FROM pg_attribute WHERE attrelid = 'events'::regclass AND attname = 'flagged'"
    ).fetchone()[0]
    assert (
        connection.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'flagged_not_null'").fetchone()[0] == 0
    )

```

After the three moves the column must really be `NOT NULL` (`attnotnull` in `pg_attribute`), and the helper constraint `flagged_not_null` must have been removed (`pg_constraint` count is zero), because once the column property is set the constraint is redundant.

`tests/integration/test_lesson_outcomes.py`, lines 150 to 163:

```python
def test_step6_a_plan_flips_on_stale_statistics_and_is_fixed_by_extended_statistics(scenarios, connection):
    flip = scenarios.plan_flip()
    stale, analyzed, extended = (flip.plans[name] for name in sorted(flip.plans))
    assert flip.actual_rows == 150_000
    assert stale.estimate * 1000 < flip.actual_rows, "the planner expected one row"
    assert stale.scans_everything
    assert analyzed.estimate * 2 < flip.actual_rows, "ANALYZE still multiplies region by city as if independent"
    assert analyzed.walks_the_index
    assert abs(extended.estimate - flip.actual_rows) <= 0.1 * flip.actual_rows, "extended statistics know the pair"
    assert stale.milliseconds > 20 * extended.milliseconds
    kinds = connection.execute("SELECT kinds FROM pg_stats_ext WHERE statistics_name = 'events_region_city'").fetchone()
    assert kinds is not None
    assert sorted(kinds[0]) == ["f", "m"], "functional dependencies and mcv"
    assert parse_flip_plan(flip.lines["f3_after_extended_statistics"]).estimate == extended.estimate
```

Step 6 shows a plan flipping. `scenarios.plan_flip()` loads a month of correlated data and captures the plan at three moments. `sorted(flip.plans)` sorts the names, and the generator unpacks them in order into `stale`, `analyzed` and `extended`. The true number of rows is 150,000. Before any statistics exist for the new rows, the planner expected one row (`stale.estimate * 1000 < actual`) and chose to scan everything. After a plain `ANALYZE` it still estimates less than half the truth, because it multiplies the selectivity of region by that of city as if the two were independent, but now it walks the index. With extended statistics, which tell the planner that the two columns are related, the estimate is within 10 percent of the truth. The stale plan took more than 20 times as long as the final one. The `pg_stats_ext` view shows the statistics kinds as `["f", "m"]` (`f` functional dependencies and `m` most-common-values lists), and the line `parse_flip_plan(flip.lines[...]).estimate` checks that the saved text of the third plan gives the same estimate as the stored outcome.

`tests/integration/test_lesson_outcomes.py`, lines 166 to 193:

```python
def test_migrations_run_twice_and_revert_twice_in_reverse_order_without_harm(changes, connection):
    small = {"first_id": 1, "last_id": 5000}
    changes.apply(1)
    changes.apply(1)
    changes.backfill_flagged(500_000, 0, lambda: False)
    changes.apply(2, small)
    changes.apply(2, small)
    for number in (3, 4, 5, 6):
        changes.apply(number)
        changes.apply(number)
    assert changes.unflagged_rows() == 0
    assert (
        connection.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'flagged_not_null'").fetchone()[0] == 0
    )
    for number in (6, 5, 4, 3):
        changes.apply(number, down=True)
        changes.apply(number, down=True)
    changes.apply(2, small, down=True)
    changes.apply(2, small, down=True)
    assert changes.unflagged_rows() == 5000, "the down script of the backfill puts NULL back in its range"
    for _ in range(2):
        changes.apply(1, down=True)
    columns = {
        row[0]
        for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'events'")
    }
    assert "flagged" not in columns
    assert changes.invalid_indexes() == []
```

Migrations must be safe to run twice and revert twice. The dictionary `small` holds a small id range for the backfill. The first loop applies migrations 1, 2, 3, 4, 5 and 6 each twice (`changes.apply(number)` runs the up script; 2 takes a range). Afterwards no row may be left unflagged and the helper constraint must be gone. The second loop reverts 6, 5, 4 and 3 in reverse order, twice each; reverting migration 2 puts NULL back in its 5000-row range, which the assertion checks; migration 1 is reverted twice and the column must be gone and no invalid index may remain. The set comprehension collects column names from `information_schema.columns`.

`tests/integration/test_lesson_outcomes.py`, lines 196 to 201:

```python
def test_the_schema_and_seed_scripts_can_run_twice(connection):
    run_file(connection, SQL / "001_schema.sql")
    run_file(connection, SQL / "001_schema.sql")
    assert connection.execute("SELECT count(*) FROM events").fetchone()[0] > 0
    seed = (SQL / "002_seed.sql").read_text()
    assert "\\if :events_empty" in seed
```

The schema script is run twice on purpose, and the table must still have rows afterwards. The seed script must also leave a table with rows alone: it does so with the `psql` conditional `\if :events_empty`, and the test checks that the guard is in the script text.

`tests/integration/test_lesson_outcomes.py`, lines 204 to 214:

```python
def test_the_lab_resets_to_the_seed(table, connection):
    table.reset()
    seed_rows = connection.execute("SELECT value FROM lab_meta WHERE key = 'seed_max_id'").fetchone()[0]
    assert table.row_count() == seed_rows
    columns = {
        row[0]
        for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'events'")
    }
    assert not columns & {"flagged", "scratch", "conflict_probe"}
    indexes = {row[0] for row in connection.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'events'")}
    assert indexes == {"events_pkey", "idx_events_created_at"}
```

`table.reset()` returns the lab to its seed. The row count must equal the value recorded in the `lab_meta` table under `seed_max_id`. None of the lesson's added columns (`flagged`, `scratch`, `conflict_probe`) may remain, and the only indexes must be the primary key and the `created_at` index.

`tests/integration/test_lesson_outcomes.py`, lines 217 to 226:

```python
def test_a_database_that_cannot_be_reached_is_reported_by_a_named_error(settings):
    import dataclasses

    from locks_lab.application.health import ProbeFailedError
    from locks_lab.infrastructure.health_probes import PostgresEventsProbe

    unreachable = dataclasses.replace(settings.postgres, port=1, connect_timeout_seconds=1)
    with pytest.raises(ProbeFailedError, match="cannot query PostgreSQL"):
        PostgresEventsProbe(unreachable).check()
    assert psycopg  # the failure is a PostgreSQL error wrapped in the named one
```

If the database cannot be reached, the health probe must say so with the lab's own error, `ProbeFailedError`, whose message contains `cannot query PostgreSQL`. `dataclasses.replace` makes a copy of the settings with port 1 and a one second timeout. The last line, `assert psycopg`, is a small trick that uses the imported driver module so that the linter does not report it as unused; the comment says the error is a PostgreSQL error wrapped in the named one.

### Integration tests with the load running

`tests/integration/conftest.py`, lines 20 to 70:

```python
BASELINE_SECONDS = 8


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture
def table(settings: Settings) -> Iterator[PostgresLabTable]:
    """The events table, back to the seed before the test and again after it."""
    lab = PostgresLabTable(settings.postgres)
    lab.reset()
    yield lab
    lab.reset()


@pytest.fixture
def changes(settings: Settings, table: PostgresLabTable) -> PostgresSchemaChanges:
    return PostgresSchemaChanges(settings.postgres, settings.sql_dir)


@pytest.fixture
def scenarios(settings: Settings, table: PostgresLabTable, changes: PostgresSchemaChanges) -> Scenarios:
    return Scenarios(
        table=table,
        locks=PostgresLockExperiments(settings.postgres),
        changes=changes,
        flip=PostgresPlanFlip(settings.postgres, settings.sql_dir),
        pause=time.sleep,
    )


@pytest.fixture
def load(settings: Settings, table: PostgresLabTable) -> Iterator[ThreadedLoad]:
    """The load script, running for the whole test (stopped before the table is reset)."""
    with ThreadedLoad(settings.postgres, settings.load) as running:
        yield running


@pytest.fixture
def connection(settings: Settings) -> Iterator[psycopg.Connection[Any]]:
    with postgres.session(settings.postgres) as live:
        yield live


def bracket(load: ThreadedLoad, middle: Any) -> tuple[WindowSummary, Any, WindowSummary]:
    """A baseline before and after a change: other work on the machine moves p99 as much as a migration does."""
    before = load.measure(BASELINE_SECONDS)
    result = middle()
    return before, result, load.measure(BASELINE_SECONDS)
```

`BASELINE_SECONDS = 8` (short windows). Session fixture `settings`. `table` resets the table to the seed **before** the test and again after it. `changes` and `scenarios` build the real adapters. `load` is a fixture that starts the load for the whole test: `with ThreadedLoad(...) as running: yield running` — the load stops when the test ends, before the table is reset (the fixture dependency order does it: `load` depends on `table`). `bracket(load, middle)` measures a baseline before and after a change and returns both with the change's result: "other work on the machine moves p99 as much as a migration does".

`tests/integration/test_lesson_outcomes.py`, lines 51 to 78:

```python
def test_step3_the_safe_migration_keeps_p99_within_twice_baseline_and_a_forced_conflict_fails_fast(
    load, scenarios, connection, settings
):
    def relfilenode() -> int:
        return int(connection.execute("SELECT relfilenode FROM pg_class WHERE oid = 'events'::regclass").fetchone()[0])

    before_file = relfilenode()

    def migrate_safely():
        conflict = scenarios.forced_conflict("1s")
        return conflict, scenarios.safe_migration(load, settings.migration.batch_size, settings.migration.pause_seconds)

    before, (conflict, safe), after = bracket(load, migrate_safely)
    bar = Bar.bracketing(before, after)
    assert conflict.failed_fast
    assert 0.9 <= conflict.seconds < 2.5, "it gave up at lock_timeout instead of queueing"
    assert relfilenode() == before_file, "adding the column rewrote nothing"
    assert safe.summary.errors == 0
    assert safe.summary.stalled_seconds == 0
    assert safe.summary.p99_ms <= bar.limit_ms, f"p99 {safe.summary.p99_ms} ms against a bar of {bar.limit_ms} ms"
    assert safe.rows_still_null == 0
    assert safe.batches >= 50
    default = connection.execute(
        "SELECT column_default FROM information_schema.columns WHERE table_name = 'events' AND column_name = 'flagged'"
    ).fetchone()
    assert default is not None
    assert default[0] == "false", "rows inserted during the migration got a value from the default"

```

The test of the safe migration: `relfilenode()` reads the table's file number (adding the column rewrote nothing, so it is unchanged); `bracket(...)` measures the baselines around `migrate_safely()`; `Bar.bracketing(before, after)` gives the pass mark; the assertions check the forced conflict failed fast (between 0.9 and 2.5 seconds), no errors, no stalled second, p99 within twice the baseline, no NULLs left, at least 50 batches, and that the column's default is `false`. A test that depends on timing says in its assertion messages what a failure means.

`tests/integration/test_lesson_outcomes.py`, lines 195 to 226:

```python

def test_the_schema_and_seed_scripts_can_run_twice(connection):
    run_file(connection, SQL / "001_schema.sql")
    run_file(connection, SQL / "001_schema.sql")
    assert connection.execute("SELECT count(*) FROM events").fetchone()[0] > 0
    seed = (SQL / "002_seed.sql").read_text()
    assert "\\if :events_empty" in seed


def test_the_lab_resets_to_the_seed(table, connection):
    table.reset()
    seed_rows = connection.execute("SELECT value FROM lab_meta WHERE key = 'seed_max_id'").fetchone()[0]
    assert table.row_count() == seed_rows
    columns = {
        row[0]
        for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'events'")
    }
    assert not columns & {"flagged", "scratch", "conflict_probe"}
    indexes = {row[0] for row in connection.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'events'")}
    assert indexes == {"events_pkey", "idx_events_created_at"}


def test_a_database_that_cannot_be_reached_is_reported_by_a_named_error(settings):
    import dataclasses

    from locks_lab.application.health import ProbeFailedError
    from locks_lab.infrastructure.health_probes import PostgresEventsProbe

    unreachable = dataclasses.replace(settings.postgres, port=1, connect_timeout_seconds=1)
    with pytest.raises(ProbeFailedError, match="cannot query PostgreSQL"):
        PostgresEventsProbe(unreachable).check()
    assert psycopg  # the failure is a PostgreSQL error wrapped in the named one
```

Tests without the load: the schema and seed scripts run twice, the lab resets to the seed (the column and extra indexes are gone, the row count equals the seed's), and an unreachable database is reported by a named error: `dataclasses.replace(settings.postgres, port=1, connect_timeout_seconds=1)` makes a copy of the settings with another port (nothing listens on port 1), and `pytest.raises(ProbeFailedError, match="cannot query PostgreSQL")` checks the error.

### End-to-end tests

`tests/e2e/test_replay.py`, lines 1 to 52:

```python
"""The lesson's scenario through the command-line programs, as the Makefile runs them (make up db first)."""

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e

# A shared machine can take longer than the 5 s default to accept a connection while the replay runs.
SLOW_MACHINE = {"PG_CONNECT_TIMEOUT_SECONDS": os.environ.get("PG_CONNECT_TIMEOUT_SECONDS", "30")}


def program(module: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", f"locks_lab.interfaces.{module}", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **SLOW_MACHINE, **env},
        timeout=1800,
        check=False,
    )


def test_the_health_command_is_green_on_the_seeded_database():
    result = program("health_cli")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok postgres:" in result.stdout


def test_the_load_command_reports_a_steady_rate_as_json():
    result = program("load_cli", "--seconds", "4")
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout[result.stdout.index("{") :])
    assert summary["errors"] == 0
    assert summary["ops_per_second"] > 80


def test_the_replay_writes_the_notes_the_lock_queue_and_the_three_plans(tmp_path):
    result = program(
        "run_cli", "--baseline-seconds", "8", "--output-dir", str(tmp_path), CLOSING_SECONDS="8", LOG_LEVEL="WARNING"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    notes = (tmp_path / "results.md").read_text()
    assert "| 1 baseline, opening |" in notes
    assert "## Step 6: the plan flip" in notes
    assert "naive-alter" in (tmp_path / "lock_queue.txt").read_text()
    assert "Seq Scan on events" in (tmp_path / "f1_stale_statistics.txt").read_text()
    assert "Index Scan Backward" in (tmp_path / "f3_after_extended_statistics.txt").read_text()
    assert "safe migration p99" in result.stdout
```

`SLOW_MACHINE` is a dictionary with one environment variable, `PG_CONNECT_TIMEOUT_SECONDS`, defaulting to `30`: on a busy machine the commands get 30 seconds to be accepted by the database. `program(module, *args, **env)` starts a command with `subprocess.run([...], capture_output=True, text=True, env={**os.environ, **SLOW_MACHINE, **env}, timeout=1800, check=False)`. The load test runs `load_cli --seconds 4` and parses the summary JSON from the output (`json.loads(result.stdout[result.stdout.index("{") :])`: everything from the first `{`). The replay test runs the whole lesson with 8-second baselines into a temporary folder and checks the files it wrote.

## Try it yourself

1. `make test` — `90 passed` for the unit tests, then the coverage table, ending with the coverage report for the domain and application folders.
2. `.venv/bin/python -m pytest tests/unit/domain -q` — only the domain tests.
3. `.venv/bin/python -m pytest tests/unit -q -k percentile` — runs only tests whose name contains `percentile`.
4. `.venv/bin/python -m pytest --markers | head` — lists the markers, including the project's two.
5. `.venv/bin/python -m pytest tests/unit/domain/test_stats.py -q -vv` — verbose names; try breaking an assertion in a scratch copy (change `99.0` to `98.0`) to see pytest print the two values.
6. With the database up: `make test-integration` (13 tests, about 4 minutes: they run real windows of load) and `make test-e2e` (3 tests, a few minutes).

## Mistakes people make

- A test that depends on another test running first.
- Tests that read the real clock, random numbers or the network and so fail sometimes.
- Asserting too little (a test that cannot fail).
- Catching the error inside the test instead of using `pytest.raises`.
- Leaving shared state (a database table) changed after a test.
- Naming a test file or function without the `test` prefix, so pytest never runs it.

**How this repository avoids them.** Unit tests never touch the network, threads or the clock (the fakes script them). Integration tests reset the table before and after each test and bracket a change with baselines instead of trusting one number. Markers are declared and `--strict-markers` is on. Failing-path tests use `pytest.raises` with `match`.

## Check yourself

1. How does pytest know which functions are tests? *They are named `test_*` in files named `test_*.py`.*
2. What is a fixture? *A function that prepares something for tests; a test receives it by naming it as a parameter.*
3. What does `tmp_path` give? *A new empty temporary folder, different for each test.*
4. What does `pytest -m integration` do? *Runs only the tests marked `integration`.*
5. What does `--strict-markers` protect against? *Misspelled or undeclared marker names being silently accepted.*

## Further reading

- pytest documentation (9.1): https://docs.pytest.org/en/stable/ — "Get Started", "How to use fixtures", "How to parametrize", "How to monkeypatch", "How to capture stdout/stderr".

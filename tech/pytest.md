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

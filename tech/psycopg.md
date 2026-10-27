# psycopg 3

## What it is

**psycopg** (version 3) is the Python library that talks to a PostgreSQL server. Your Python code opens a **connection**, sends SQL text, and receives rows back as Python values. Underneath it uses **libpq**, the C library from PostgreSQL itself that implements the network protocol.

## Why this repository uses it

Everything the lab does to the database goes through psycopg: the load's statements, the migration files, the lock experiments, the observer that reads the lock views, the plan-flip experiment, the reset and the health check. It is the only third-party package the programs need at run time (pinned as `psycopg==3.3.6` and `psycopg-binary==3.3.6`). The lesson's experiments need *several connections at once* with different roles, which is easy with psycopg because a connection is just an object.

## Where it appears

| File | Use |
|---|---|
| `infrastructure/postgres.py` | `connect`, `session`, `scalar`: every connection is opened here, with an `application_name`. |
| `infrastructure/load_runner.py` | One connection per worker thread; the three statements. |
| `infrastructure/lock_experiments.py` | The long read, the naive and the safe `ALTER`, the observer; `dict_row`. |
| `infrastructure/schema_changes.py` | Runs migration files with retry on `LockNotAvailable`; the concurrent index and its cancellation. |
| `infrastructure/lab_table.py` | The reset. |
| `infrastructure/plan_flip.py` | The correlated month, `ANALYZE`, `CREATE STATISTICS`, the three plans. |
| `infrastructure/health_probes.py` | The health queries and the translation of `psycopg.Error`. |
| `infrastructure/sql_script.py` | `run_file` runs statements on a connection. |
| `domain/` and `application/` | Never import psycopg (import-linter forbids it). |

## How it works underneath

**Connection.** `psycopg.connect(host=..., port=..., dbname=..., user=..., password=..., connect_timeout=...)` opens a network (TCP) connection to the server, which starts a dedicated server process for it, and logs in. `connect_timeout` limits how long to wait, in seconds. The keyword `options` passes server settings for the session in the form `-c name=value`.

**Cursor and `execute`.** A **cursor** sends a statement and holds its result. `connection.execute("SELECT ...")` is a shortcut: it creates a cursor, runs the statement and returns the cursor. `cursor.fetchone()` returns the next row (a Python tuple) or `None`; `fetchall()` returns all remaining rows as a list. `cursor.description` is `None` when the statement returns no rows (an `INSERT`, `CREATE INDEX`...) and describes the columns when it does.

**Parameters.** `execute("... WHERE id = %s", (5,))` sends the value separately from the statement text (the server substitutes it, "server-side binding"). Never build SQL by pasting user text into a string: that is how SQL injection happens. A table or index *name* cannot be a parameter; code that must put a name into SQL builds the text itself, from a fixed list.

**Transactions and autocommit.** A **transaction** is a group of statements that succeed or fail together. With `autocommit=False` (the default) psycopg opens a transaction before your first statement and keeps it open until you call `commit()` or `rollback()`, or leave a `with connection:` block. With `autocommit=True` each statement is its own transaction and is saved at once. Some commands cannot run inside a transaction (`VACUUM`, `CREATE INDEX CONCURRENTLY`), so they need autocommit.

**Types.** Python `int`, `str`, `float`, `datetime`, `Decimal`, `list`, `dict` (as JSON) are converted to and from PostgreSQL types automatically. A row is a tuple unless you ask for something else.

**Errors.** Base class `psycopg.Error`; `psycopg.OperationalError` for connection problems and server shutdowns; `psycopg.errors.QueryCanceled` when a statement hits `statement_timeout`; many others named after PostgreSQL error codes.

**Installing.** `pip install "psycopg[binary]"` installs `psycopg` plus `psycopg-binary`, a precompiled version bundled with libpq, which needs no compiler and no PostgreSQL client libraries. `psycopg[c]` builds from source. Plain `psycopg` is pure Python and needs a libpq installed on the system.

**Closing.** A connection holds a server process; close it (`connection.close()`) or use a `with` block.

## Walkthrough of this repository's use

### Opening a connection

`src/locks_lab/infrastructure/postgres.py`, lines 1 to 77:

```python
"""Adapter: connections to PostgreSQL, with a connect timeout, a statement timeout and retries with backoff."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from .logging import fields
from .retry import retry
from .settings import PostgresSettings

logger = logging.getLogger(__name__)


def connect(
    settings: PostgresSettings,
    attempts: int = 5,
    *,
    autocommit: bool = True,
    application_name: str = "locks-lab",
    statement_timeout_ms: int | None = None,
) -> psycopg.Connection[Any]:
    """Open a connection; parallel query is off for the session so plans read the same on every server.

    `application_name` is what the lock views show, so each actor in an experiment can be told apart.
    """
    timeout = settings.statement_timeout_ms if statement_timeout_ms is None else statement_timeout_ms

    def open_connection() -> psycopg.Connection[Any]:
        return psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.database,
            user=settings.user,
            password=settings.password,
            connect_timeout=settings.connect_timeout_seconds,
            options=(
                f"-c statement_timeout={timeout} "
                f"-c max_parallel_workers_per_gather={settings.max_parallel_workers_per_gather}"
            ),
            autocommit=autocommit,
            application_name=application_name,
        )

    return retry(
        open_connection,
        attempts=attempts,
        base_delay_seconds=0.5,
        retry_on=(psycopg.OperationalError,),
        on_retry=lambda attempt, error: logger.warning(
            "retrying database connection", extra=fields(attempt=attempt, error=error)
        ),
    )


@contextmanager
def session(
    settings: PostgresSettings, *, autocommit: bool = True, application_name: str = "locks-lab"
) -> Iterator[psycopg.Connection[Any]]:
    """A connection that is always closed, also when the block raises."""
    connection = connect(settings, autocommit=autocommit, application_name=application_name)
    try:
        yield connection
    finally:
        connection.close()


def scalar(connection: psycopg.Connection[Any], query: str) -> Any:
    """The first column of the first row of a query that must return one."""
    row = connection.execute(query).fetchone()
    if row is None:
        raise LookupError(f"query returned no row: {query[:60]}")
    return row[0]
```

- `connect(settings, attempts=5, *, autocommit=True, application_name="locks-lab", statement_timeout_ms=None)` returns a `psycopg.Connection[Any]`. The new parameter `application_name` is sent to the server and shows up in `pg_stat_activity` and in the lock views: it is how the experiments tell the *long-transaction*, *naive-alter*, *load*, *migration* and *lab-observer* sessions apart. `statement_timeout_ms=None` means "use the settings' value (10 minutes)"; the load passes its own 3 seconds.
- `psycopg.connect(...)` gets host, port, database name (`dbname=`), user, password, `connect_timeout`, `autocommit` and `application_name`; `options=(f"-c statement_timeout={timeout} " f"-c max_parallel_workers_per_gather={...}")` sets two server settings for this session only.
- `retry(open_connection, attempts=attempts, base_delay_seconds=0.5, retry_on=(psycopg.OperationalError,), ...)` retries only connection failures with exponential backoff (standard-library note), logging each failed attempt.
- `session(...)` wraps the connection in a context manager that always closes it; `scalar` returns `row[0]` of a query that must return a row.

### Roles and transactions in the lock experiments

`src/locks_lab/infrastructure/lock_experiments.py`, lines 58 to 62:

```python
    def _long_read(self) -> psycopg.Connection[Any]:
        """Session A: a transaction that has only read, left open. The caller rolls it back to release it."""
        connection = connect(self._settings, autocommit=False, application_name="long-transaction")
        connection.execute("SELECT * FROM events WHERE id = 1").fetchall()
        return connection
```

`connect(self._settings, autocommit=False, application_name="long-transaction")`: with `autocommit=False` psycopg opens a **transaction** before the first statement and keeps it open. `connection.execute("SELECT * FROM events WHERE id = 1").fetchall()` runs a read, which takes a lock on the table (`AccessShareLock`) that lasts until the transaction ends. The method returns the connection with the transaction still open: the caller ends it later with `.rollback()`. That open, read-only transaction is the "long read" of the lesson's second step.

`src/locks_lab/infrastructure/lock_experiments.py`, lines 90 to 105:

```python
    def forced_conflict(self, lock_timeout: str) -> ConflictOutcome:
        """A long read is open and the safe ALTER has a lock_timeout. It must fail fast, not queue."""
        long_transaction = self._long_read()
        try:
            with connect(self._settings, application_name="safe-alter") as connection:
                connection.execute(f"SET lock_timeout = '{lock_timeout}'")
                started = time.perf_counter()
                try:
                    connection.execute("ALTER TABLE events ADD COLUMN conflict_probe boolean")
                    failed = False
                except errors.LockNotAvailable:
                    failed = True
                return ConflictOutcome(failed, time.perf_counter() - started)
        finally:
            long_transaction.rollback()
            long_transaction.close()
```

The safe `ALTER`: `connection.execute(f"SET lock_timeout = '{lock_timeout}'")` limits how long this session waits for any lock (the value was validated by a regular expression at start-up; it is not user text). `connection.execute("ALTER TABLE events ADD COLUMN conflict_probe boolean")` then waits for the lock the long read blocks, gives up after the timeout and raises `psycopg.errors.LockNotAvailable` (SQLSTATE `55P03`); `except errors.LockNotAvailable: failed = True` records it. `psycopg.errors` has one class per PostgreSQL error code. The `with connect(...) as connection:` form closes the connection at the end of the block (a psycopg connection is itself a context manager; unlike `session`, it also commits or rolls back an open transaction on exit).

### Reading the lock views with named columns

`src/locks_lab/infrastructure/lock_experiments.py`, lines 22 to 49:

```python
_WAITING = """
SELECT pid, application_name, pg_blocking_pids(pid) AS blocked_by, left(query, 70) AS query,
       round(extract(epoch FROM now() - query_start)::numeric, 1) AS waiting_seconds
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid() AND wait_event_type = 'Lock'
ORDER BY query_start
"""
_QUEUE = """
SELECT l.pid, a.application_name, l.mode, l.granted
FROM pg_locks l JOIN pg_stat_activity a USING (pid)
WHERE l.relation = 'events'::regclass AND l.locktype = 'relation'
ORDER BY l.granted DESC, a.query_start
"""


def snapshot_locks(connection: psycopg.Connection[Any]) -> LockSnapshot:
    """The lock queue on the events table right now: who waits for whom, and which requests are queued."""
    cursor = connection.cursor(row_factory=dict_row)
    waiting = tuple(
        WaitingSession(
            row["pid"], row["application_name"], tuple(row["blocked_by"]), float(row["waiting_seconds"]), row["query"]
        )
        for row in cursor.execute(_WAITING)
    )
    queue = tuple(
        LockRequest(row["pid"], row["application_name"], row["mode"], row["granted"]) for row in cursor.execute(_QUEUE)
    )
    return LockSnapshot(waiting, queue)
```

`cursor = connection.cursor(row_factory=dict_row)` creates a cursor whose rows come back as **dictionaries** (`row["pid"]`) instead of tuples. The two queries select from `pg_stat_activity` and `pg_locks` (PostgreSQL notes); `for row in cursor.execute(_WAITING)` iterates the rows directly. `pg_blocking_pids(pid)` returns the list of process ids blocking a session; psycopg turns the PostgreSQL array into a Python list, which the code converts to a tuple.

### Migration files with retry

`src/locks_lab/infrastructure/schema_changes.py`, lines 51 to 79:

```python
    # -- running a migration file under lock_timeout, with retries -----------------------------------------------
    def apply(self, number: int, params: dict[str, int] | None = None, *, down: bool = False) -> int:
        """Run a migration file; on lock_timeout wait and run it again. Returns the attempts it took."""
        path = migration_file(self._sql_dir, number, down=down)
        attempts_used = 0

        def attempt() -> None:
            nonlocal attempts_used
            attempts_used += 1
            with session(self._settings, application_name="migration") as connection:
                try:
                    run_file(connection, path, params)
                except errors.LockNotAvailable:
                    connection.execute("ROLLBACK")  # the file may have opened a transaction block
                    raise

        try:
            retry(
                attempt,
                attempts=LOCK_RETRIES,
                base_delay_seconds=0.5,
                retry_on=(errors.LockNotAvailable,),
                on_retry=lambda n, _error: logger.warning(
                    "lock_timeout, retrying", extra=fields(migration=number, attempt=n)
                ),
            )
        except errors.LockNotAvailable as error:
            raise LockWaitTimeoutError(f"migration {number} could not get its lock in {LOCK_RETRIES} tries") from error
        return attempts_used
```

`apply(number, params=None, *, down=False)` runs a migration file (`run_file`, standard-library note) on a fresh connection named `migration`. If the file's `lock_timeout` expires, PostgreSQL raises `LockNotAvailable`; the inner function rolls back whatever transaction block the file opened (`connection.execute("ROLLBACK")`) and re-raises, `retry(...)` waits (backoff) and runs the whole attempt again, up to 10 times (`LOCK_RETRIES`). `attempts_used` counts the tries (`nonlocal` lets the inner function change the variable of the outer one). After the last failure the error is translated into the lab's `LockWaitTimeoutError`.

### Cancelling a statement on purpose

`src/locks_lab/infrastructure/schema_changes.py`, lines 123 to 162:

```python
    def interrupted_concurrent_build(self, phase: str = "index validation", attempts: int = 5) -> InterruptedBuild:
        """Start CREATE INDEX CONCURRENTLY in another session and cancel it once it reaches `phase`.

        Cancelled in its validation phase the index is already marked ready (so every write maintains it) but never
        became valid (so no query can use it). That is the leftover the lesson wants found. The build is quick on a
        small table, so a cancel that arrives too late is cleaned up and tried again.
        """
        path = migration_file(self._sql_dir, 3)
        cancelled = False
        with session(self._settings, application_name="lab-observer") as observer:
            for _ in range(attempts):
                outcome: dict[str, bool] = {}

                def build(outcome: dict[str, bool] = outcome) -> None:
                    with session(self._settings, application_name="index-build") as builder:
                        try:
                            run_file(builder, path)
                        except errors.QueryCanceled:
                            outcome["cancelled"] = True

                thread = threading.Thread(target=build, name="index-build")
                thread.start()
                while thread.is_alive():
                    row = observer.execute(
                        "SELECT pid FROM pg_stat_progress_create_index WHERE phase LIKE %s", (phase + "%",)
                    ).fetchone()
                    if row:
                        observer.execute("SELECT pg_cancel_backend(%s)", (row[0],))
                        break
                    time.sleep(0.01)
                thread.join()
                cancelled = outcome.get("cancelled", False)
                if cancelled:
                    break
                observer.execute(f"DROP INDEX IF EXISTS {DEVICE_INDEX}")  # finished before the cancel: try again
            state = observer.execute(
                f"SELECT indisvalid, indisready FROM pg_index WHERE indexrelid = to_regclass('{DEVICE_INDEX}')"
            ).fetchone()
        ready_but_invalid = state is not None and bool(state[1]) and not state[0]
        return InterruptedBuild(cancelled, tuple(self.invalid_indexes()), ready_but_invalid)
```

The observer connection polls `SELECT pid FROM pg_stat_progress_create_index WHERE phase LIKE %s` with the parameter `(phase + "%",)` (a trailing `%` makes `LIKE` match any text that begins with the phase) and calls `SELECT pg_cancel_backend(%s)`, which asks the server to cancel the running statement of that process. The builder's connection then receives `psycopg.errors.QueryCanceled` (SQLSTATE `57014`), caught by `except errors.QueryCanceled: outcome["cancelled"] = True`. The cancelled `CREATE INDEX CONCURRENTLY` leaves an invalid index behind (PostgreSQL note).

### Reading the transaction's locks

`src/locks_lab/infrastructure/schema_changes.py`, lines 181 to 214:

```python
    def _report(self, statements: Iterable[str], lock_timeout: str = "2s") -> LockReport:
        """Run statements in one transaction; report the lock modes it held on events, how long it took, and tries."""

        def attempt(connection: psycopg.Connection[Any]) -> LockReport:
            connection.execute("BEGIN")
            try:
                started = time.perf_counter()
                for statement in statements:
                    connection.execute(statement)
                seconds = time.perf_counter() - started
                modes = tuple(
                    row[0]
                    for row in connection.execute(
                        "SELECT mode FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'relation' "
                        "AND relation = 'events'::regclass ORDER BY mode"
                    )
                )
                connection.execute("COMMIT")
                return LockReport(seconds, modes)
            except psycopg.Error:
                connection.execute("ROLLBACK")
                raise

        with session(self._settings, application_name="migration") as connection:
            connection.execute(f"SET lock_timeout = '{lock_timeout}'")
            tries = 0

            def counted() -> LockReport:
                nonlocal tries
                tries += 1
                return attempt(connection)

            report = retry(counted, attempts=LOCK_RETRIES, base_delay_seconds=1.0, retry_on=(errors.LockNotAvailable,))
        return LockReport(report.seconds, report.lock_modes, tries)
```

`_report` runs statements inside an explicit `BEGIN ... COMMIT` on an autocommit connection, measuring the time and, before committing, asking which table locks this very session holds: `SELECT mode FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'relation' AND relation = 'events'::regclass ORDER BY mode`. `pg_backend_pid()` is the server process id of the current session. The result is the lock mode report in `results.md` ("Lock held"). On a `psycopg.Error` it issues `ROLLBACK` and re-raises; the surrounding `retry` repeats only on `LockNotAvailable`.

### Reset, plan flip and health

`src/locks_lab/infrastructure/lab_table.py`, lines 24 to 59:

```python
class PostgresLabTable:
    """Puts the table back to the seed and reports facts about it."""

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings

    def reset(self) -> None:
        """Remove what the lab added: column, indexes, constraint, statistics, and every row beyond the seed.

        DDL runs under a lock_timeout and is retried, so a reset never joins a lock queue for good.
        """
        with session(self._settings, application_name="lab-reset") as connection:
            connection.execute("SET lock_timeout = '5s'")
            for statement in _RESET_STATEMENTS:
                try:
                    retry(
                        lambda: connection.execute(statement),  # noqa: B023  (called inside this iteration)
                        attempts=10,
                        base_delay_seconds=1.0,
                        retry_on=(errors.LockNotAvailable,),
                    )
                except errors.LockNotAvailable as error:
                    raise LockWaitTimeoutError(f"could not get the lock to reset the lab: {statement}") from error
            connection.execute("DELETE FROM events WHERE id > (SELECT value FROM lab_meta WHERE key = 'seed_max_id')")
            connection.execute("ALTER TABLE events RESET (autovacuum_enabled)")
            connection.execute("VACUUM (ANALYZE) events")

    def row_count(self) -> int:
        with session(self._settings) as connection:
            return int(scalar(connection, "SELECT count(*) FROM events"))

    def size(self) -> TableSize:
        with session(self._settings) as connection:
            pretty = scalar(connection, "SELECT pg_size_pretty(pg_table_size('events'))")
            dead = scalar(connection, "SELECT n_dead_tup FROM pg_stat_user_tables WHERE relname = 'events'")
        return TableSize(str(pretty), int(dead))
```

`reset()` runs seven `DROP ... IF EXISTS` statements under `SET lock_timeout = '5s'`, each inside `retry(..., retry_on=(errors.LockNotAvailable,))`, then deletes every row above the seed's highest id (`DELETE FROM events WHERE id > (SELECT value FROM lab_meta WHERE key = 'seed_max_id')`), restores the autovacuum setting and runs `VACUUM (ANALYZE) events`. `row_count` and `size` read one value each with `scalar`.

`src/locks_lab/infrastructure/plan_flip.py`, lines 14 to 42:

```python
class PostgresPlanFlip:
    """Loads a correlated month and plans the query three times: stale, after ANALYZE, after extended statistics."""

    def __init__(self, settings: PostgresSettings, sql_dir: Path) -> None:
        self._settings = settings
        self._sql_dir = sql_dir

    def run(self) -> FlipOutcome:
        plans: dict[str, tuple[str, ...]] = {}
        with session(self._settings, application_name="plan-flip") as connection:
            run_file(connection, self._sql_dir / "experiments" / "01_bulk_load_correlated_month.sql")
            actual = int(
                scalar(connection, "SELECT count(*) FROM events WHERE region = 'pacific' AND city = 'seattle'")
            )

            def capture(name: str) -> None:
                rows = run_file(connection, self._sql_dir / "explain" / f"{name}.sql")
                plans[name] = tuple(row[0] for row in rows)

            first, second, third = FLIP_PLANS
            capture(first)
            connection.execute("ANALYZE events")
            capture(second)
            connection.execute(
                f"CREATE STATISTICS {EXTENDED_STATISTICS} (dependencies, mcv) ON region, city FROM events"
            )
            connection.execute("ANALYZE events")
            capture(third)
        return FlipOutcome(actual, plans)
```

Runs the correlated-month file, counts the matching rows, then three times: capture a plan (`run_file` of an `explain/*.sql` file returns the `EXPLAIN` lines), with `ANALYZE events` and `CREATE STATISTICS ... (dependencies, mcv) ON region, city FROM events` and a second `ANALYZE` between them (PostgreSQL statistics note).

`src/locks_lab/infrastructure/health_probes.py`, lines 12 to 31:

```python
class PostgresEventsProbe:
    """Healthy when PostgreSQL answers and the events table is seeded."""

    name = "postgres"

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings

    def check(self) -> str:
        try:
            with session(self._settings) as connection:
                if scalar(connection, "SELECT to_regclass('public.events')") is None:
                    raise ProbeFailedError("the events table is missing; run make db")
                seeded = scalar(connection, "SELECT count(*) FROM lab_meta WHERE key = 'seed_max_id'")
                rows = scalar(connection, "SELECT count(*) FROM events")
        except psycopg.Error as error:
            raise ProbeFailedError(f"cannot query PostgreSQL: {error}") from error
        if seeded == 0 or rows == 0:
            raise ProbeFailedError("the events table is empty or not seeded; run make db")
        return f"{rows:,} events"
```

Three queries: `to_regclass('public.events')` is `NULL` (Python `None`) when the table does not exist; `count(*) FROM lab_meta WHERE key = 'seed_max_id'` is 1 when the seed ran; `count(*) FROM events`. Any `psycopg.Error` becomes the application's `ProbeFailedError` with `raise ... from error`.

## Try it yourself

(After `make up db`, with `.env` loaded: `set -a; . ./.env; set +a`.)

1. `make health` prints `ok postgres: 2,000,0NN events` (the seed plus rows the load script has added).
2. Ask the server three questions through a session. Run:

   ```bash
   .venv/bin/python - <<'EOF'
   from locks_lab.infrastructure.postgres import session
   from locks_lab.infrastructure.settings import Settings
   with session(Settings.from_env().postgres, application_name="try-it") as c:
       print(c.execute("select version()").fetchone()[0])
       print(c.execute("show statement_timeout").fetchone())
       print(c.execute("select application_name from pg_stat_activity where pid = pg_backend_pid()").fetchone())
   EOF
   ```

   (`python -` reads the program from standard input; `<<'EOF' ... EOF` is a **here-document**.) It prints the PostgreSQL version line, `('10min',)` and `('try-it',)`: the settings and the application name were passed at connection time.
3. A lock timeout in action, from two connections: in one terminal `make psql`, then `begin; select * from events where id = 1;` (leave it open). In another terminal run `docker compose exec db psql -U lab -d lab -c "set lock_timeout = '1s'; alter table events add column probe boolean"`: after one second it fails with `ERROR:  canceling statement due to lock timeout`. Back in the first terminal type `rollback;`.
4. `docker compose exec db psql -U lab -d lab -c "select application_name, count(*) from pg_stat_activity where datname = 'lab' group by 1 order by 1"` while `make load SECONDS=30` runs: `load` shows 4 connections.
5. `make down` and run command 2 again: you see four `retrying database connection` warnings with growing pauses (five attempts are made) and then a `psycopg.OperationalError`.

## Mistakes people make

- Building SQL with f-strings from user input.
- Leaving a transaction open (a default connection after `SELECT` is "idle in transaction", holding resources and blocking maintenance).
- Forgetting `commit()` and losing changes.
- Running `VACUUM` in a transaction (PostgreSQL refuses).
- Not closing connections.
- Assuming a fetched row is a dictionary (it is a tuple unless a row factory is chosen).

**How this repository avoids them.** Connections are always closed (`finally`). Only the migration files and the plan files are executed; no user text is pasted into SQL, and the one f-string (`DROP INDEX IF EXISTS {index}`) uses names from a constant tuple. `VACUUM` runs on an autocommit connection. The write-cost batches run in a transaction that is rolled back, and the replay checks that the row count did not change.

## Check yourself

1. What does `connection.execute(sql)` return? *A cursor holding the result.*
2. When does `cursor.description` equal `None`? *When the statement returns no rows.*
3. What does `autocommit=True` change? *Every statement is committed on its own; no transaction stays open.*
4. Why pass values as parameters (`%s`) and not paste them into the SQL? *To avoid SQL injection and quoting errors; the value never becomes part of the statement text.*
5. What is `psycopg-binary`? *A precompiled, self-contained implementation that makes `pip install` need no compiler or libpq.*

## Further reading

- Psycopg 3 documentation (3.3): https://www.psycopg.org/psycopg3/docs/ — "Basic module usage", "Transactions management", "Installation".
- PostgreSQL libpq connection parameters: https://www.postgresql.org/docs/18/libpq-connect.html#LIBPQ-PARAMKEYWORDS

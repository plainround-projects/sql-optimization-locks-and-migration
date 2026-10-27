"""Adapter: the three changes of the lesson, each the naive way and the safe way. Implements `SchemaChanges`.

The safe versions run the repository's migration files; anything that needs a strong lock sets a short lock_timeout
(in the file) and is retried here, so a busy table makes the migration wait politely instead of joining the lock
queue for good.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import psycopg
from psycopg import errors

from ..domain.backfill import id_ranges
from ..domain.errors import LockWaitTimeoutError, UnknownMigrationError
from ..domain.lesson import DEVICE_INDEX
from ..domain.locks import LockReport
from ..domain.outcomes import InterruptedBuild, RebuiltIndex
from .logging import fields
from .postgres import scalar, session
from .retry import retry
from .settings import PostgresSettings
from .sql_script import run_file

logger = logging.getLogger(__name__)
LOCK_RETRIES = 10


def migration_file(sql_dir: Path, number: int, *, down: bool = False) -> Path:
    """The migration whose file name starts with the number (the down script when `down`)."""
    folder = sql_dir / "migrations" / ("down" if down else "")
    matches = sorted(folder.glob(f"{number:03d}_*.sql"))
    if not matches:
        raise UnknownMigrationError(f"there is no {'down ' if down else ''}migration {number}")
    return matches[0]


class PostgresSchemaChanges:
    """Applies the lesson's changes to the events table."""

    def __init__(self, settings: PostgresSettings, sql_dir: Path) -> None:
        self._settings = settings
        self._sql_dir = sql_dir

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

    # -- step 3 --------------------------------------------------------------------------------------------------
    def add_flagged_column(self) -> int:
        return self.apply(1)

    def backfill_flagged(self, batch_size: int, pause_seconds: float, should_stop: Callable[[], bool]) -> int:
        """Fill `flagged` for the rows that exist now, `batch_size` ids at a time, pausing between batches.

        Rows inserted after the column was added already have a value (the default), so the range stops at the
        highest id seen when the backfill starts. Each batch only touches rows still NULL, so a stopped backfill can
        simply be started again. Stops between batches when `should_stop()` is true.
        """
        with session(self._settings, application_name="migration") as connection:
            last_id = int(scalar(connection, "SELECT max(id) FROM events"))
        batches = 0
        for first_id, last in id_ranges(1, last_id, batch_size):
            if should_stop():
                break
            self.apply(2, {"first_id": first_id, "last_id": last})
            batches += 1
            time.sleep(pause_seconds)
        return batches

    def unflagged_rows(self) -> int:
        with session(self._settings) as connection:
            return int(scalar(connection, "SELECT count(*) FROM events WHERE flagged IS NULL"))

    # -- step 4 --------------------------------------------------------------------------------------------------
    def plain_index_build(self) -> float:
        with session(self._settings, application_name="naive-index") as connection:
            started = time.perf_counter()
            connection.execute("CREATE INDEX idx_events_naive ON events (device_id, created_at DESC)")
            seconds = time.perf_counter() - started
            connection.execute("DROP INDEX idx_events_naive")
        return seconds

    def invalid_indexes(self) -> list[str]:
        with session(self._settings) as connection:
            return [
                row[0]
                for row in connection.execute("SELECT indexrelid::regclass::text FROM pg_index WHERE NOT indisvalid")
            ]

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

    def rebuild_invalid_index(self) -> RebuiltIndex:
        """Drop every invalid index (concurrently) and build the lesson's index again."""
        for name in self.invalid_indexes():
            with session(self._settings, application_name="migration") as connection:
                connection.execute(f"DROP INDEX CONCURRENTLY {name}")
        started = time.perf_counter()
        with session(self._settings, application_name="migration") as connection:
            run_file(connection, migration_file(self._sql_dir, 3))
            valid = bool(
                scalar(
                    connection,
                    f"SELECT indisvalid AND indisready FROM pg_index WHERE indexrelid = '{DEVICE_INDEX}'::regclass",
                )
            )
        return RebuiltIndex(time.perf_counter() - started, valid)

    # -- step 5 --------------------------------------------------------------------------------------------------
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

    def naive_set_not_null(self) -> LockReport:
        with session(self._settings) as connection:
            connection.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS scratch boolean DEFAULT false")
        report = self._report(["ALTER TABLE events ALTER COLUMN scratch SET NOT NULL"])
        with session(self._settings) as connection:
            connection.execute("ALTER TABLE events DROP COLUMN IF EXISTS scratch")
        return report

    def not_null_in_three_moves(self) -> dict[str, LockReport]:
        """The same three moves as migrations 004 to 006, each run in its own transaction so its locks can be read."""
        return {
            "add_check_not_valid": self._report(
                [
                    "ALTER TABLE events ADD CONSTRAINT flagged_not_null CHECK (flagged IS NOT NULL) NOT VALID",
                ]
            ),
            "validate": self._report(["ALTER TABLE events VALIDATE CONSTRAINT flagged_not_null"]),
            "set_not_null": self._report(
                [
                    "ALTER TABLE events ALTER COLUMN flagged SET NOT NULL",
                    "ALTER TABLE events DROP CONSTRAINT flagged_not_null",
                ]
            ),
        }

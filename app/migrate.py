"""The safe versions of the three changes, as small functions the runner and the tests share.

Every function takes an autocommit connection. Anything that needs a strong lock sets a short lock_timeout
(in the migration file) and is retried here, so a busy table makes the migration wait politely instead of
joining the lock queue for good.
"""
import os
import threading
import time

import psycopg
from psycopg import errors

from app import db

# The lesson starts at 10,000 rows a batch with a pause. On this lab 10,000 was consistently the batch size with the
# worst load p99 (sql/explain/backfill-sweep.txt): each batch writes its WAL in one burst and the load's commits queue
# behind it. 2,000 rows with a 0.05 s pause is gentler. The right size is the largest one that keeps p99 inside the bar.
BACKFILL_BATCH = int(os.environ.get("BACKFILL_BATCH", "2000"))
BACKFILL_PAUSE_SECONDS = float(os.environ.get("BACKFILL_PAUSE_SECONDS", "0.05"))


def apply_with_retry(connection, path, attempts=10, backoff_seconds=1.0, params=None):
    """Run a migration file; on lock_timeout roll back, wait and run it again. Returns (attempts used, seconds)."""
    started = time.perf_counter()
    for attempt in range(1, attempts + 1):
        try:
            db.run_file(connection, path, params)
            return attempt, time.perf_counter() - started
        except errors.LockNotAvailable:
            connection.execute("ROLLBACK")             # the file may have opened a transaction block
            if attempt == attempts:
                raise
            time.sleep(backoff_seconds)


def apply_statement(connection, statement, attempts=10, backoff_seconds=1.0):
    """One DDL statement with the same lock_timeout-and-retry discipline as a migration file."""
    for attempt in range(1, attempts + 1):
        try:
            connection.execute(statement)
            return attempt
        except errors.LockNotAvailable:
            if attempt == attempts:
                raise
            time.sleep(backoff_seconds)


def backfill_flagged(connection, batch_size=BACKFILL_BATCH, pause_seconds=BACKFILL_PAUSE_SECONDS, progress=None):
    """Fill `flagged` for the rows that exist now, `batch_size` ids at a time, pausing between batches.

    Rows inserted after the column was added already have a value (the default), so the range stops at the
    highest id seen when the backfill starts. Each batch only touches rows still NULL, so a stopped backfill
    can simply be started again. Returns the number of batches.
    """
    last_id = connection.execute("SELECT max(id) FROM events").fetchone()[0]
    batches, first_id = 0, 1
    while first_id <= last_id:
        params = {"first_id": first_id, "last_id": first_id + batch_size - 1}
        apply_with_retry(connection, db.migration(2), backoff_seconds=0.5, params=params)
        batches += 1
        first_id += batch_size
        if progress:
            progress(first_id, last_id)
        time.sleep(pause_seconds)
    return batches


def run_with_lock_report(connection, statements, lock_timeout="2s", attempts=10):
    """Run statements in one transaction; report the lock modes it held on events, how long it took, and retries."""
    connection.execute(f"SET lock_timeout = '{lock_timeout}'")
    for attempt in range(1, attempts + 1):
        connection.execute("BEGIN")
        try:
            started = time.perf_counter()
            for statement in statements:
                connection.execute(statement)
            seconds = time.perf_counter() - started
            modes = [row[0] for row in connection.execute(
                "SELECT mode FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'relation' "
                "AND relation = 'events'::regclass ORDER BY mode")]
            connection.execute("COMMIT")
            return {"seconds": seconds, "lock_modes": modes, "attempts": attempt}
        except errors.LockNotAvailable:
            connection.execute("ROLLBACK")
            if attempt == attempts:
                raise
            time.sleep(1.0)
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise


def not_null_in_three_moves(connection):
    """NOT VALID check, VALIDATE, SET NOT NULL, each reported with the lock it held."""
    return {
        "add_check_not_valid": run_with_lock_report(connection, [
            "ALTER TABLE events ADD CONSTRAINT flagged_not_null CHECK (flagged IS NOT NULL) NOT VALID"]),
        "validate": run_with_lock_report(connection, [
            "ALTER TABLE events VALIDATE CONSTRAINT flagged_not_null"]),
        "set_not_null": run_with_lock_report(connection, [
            "ALTER TABLE events ALTER COLUMN flagged SET NOT NULL",
            "ALTER TABLE events DROP CONSTRAINT flagged_not_null"]),
    }


def invalid_indexes(connection):
    return [row[0] for row in connection.execute("SELECT indexrelid::regclass::text FROM pg_index WHERE NOT indisvalid")]


def build_index_and_interrupt(connection, phase="index validation", attempts=5):
    """Start CREATE INDEX CONCURRENTLY in another session and cancel it once it reaches `phase`.

    Cancelled in its validation phase the index is already marked ready (so every write maintains it) but never
    became valid (so no query can use it). That is the leftover the lesson wants found. The build is quick on a
    small table, so a cancel that arrives too late is cleaned up and tried again. Returns what was left behind.
    """
    for _ in range(attempts):
        outcome = {}

        def build():
            with db.connect(application_name="index-build") as builder:
                try:
                    db.run_file(builder, db.migration(3))
                    outcome["finished"] = True
                except errors.QueryCanceled:
                    outcome["cancelled"] = True

        thread = threading.Thread(target=build)
        thread.start()
        while thread.is_alive():
            row = connection.execute(
                "SELECT pid FROM pg_stat_progress_create_index WHERE phase LIKE %s", (phase + "%",)).fetchone()
            if row:
                connection.execute("SELECT pg_cancel_backend(%s)", (row[0],))
                break
            time.sleep(0.01)
        thread.join()
        if outcome.get("cancelled"):
            break
        connection.execute("DROP INDEX IF EXISTS idx_events_device_created")      # finished before the cancel: again
    state = connection.execute(
        "SELECT indisvalid, indisready FROM pg_index WHERE indexrelid = to_regclass('idx_events_device_created')").fetchone()
    return {"cancelled": outcome.get("cancelled", False), "invalid": invalid_indexes(connection),
            "ready_but_invalid": bool(state) and state[1] and not state[0]}


def drop_invalid_and_rebuild(connection):
    for name in invalid_indexes(connection):
        connection.execute(f"DROP INDEX CONCURRENTLY {name}")
    started = time.perf_counter()
    db.run_file(connection, db.migration(3))
    return time.perf_counter() - started

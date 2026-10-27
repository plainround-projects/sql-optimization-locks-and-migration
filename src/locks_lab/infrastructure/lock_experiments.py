"""Adapter: the experiments that need a second session holding a lock. Implements `LockExperiments`."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import psycopg
from psycopg import errors
from psycopg.rows import dict_row

from ..domain.locks import LockRequest, LockSnapshot, WaitingSession
from ..domain.outcomes import ConflictOutcome, QueueOutcome
from .logging import fields
from .postgres import connect
from .settings import PostgresSettings

logger = logging.getLogger(__name__)

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


class PostgresLockExperiments:
    """A long read-only transaction (session A), a naive ALTER and a safe ALTER, each on its own connection."""

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings

    def _long_read(self) -> psycopg.Connection[Any]:
        """Session A: a transaction that has only read, left open. The caller rolls it back to release it."""
        connection = connect(self._settings, autocommit=False, application_name="long-transaction")
        connection.execute("SELECT * FROM events WHERE id = 1").fetchall()
        return connection

    def lock_queue(self, hold_seconds: float) -> QueueOutcome:
        """Open the read, start the naive ALTER behind it, sample the views mid-pile-up, then release the read."""
        observer = connect(self._settings, application_name="lab-observer")
        long_transaction = self._long_read()
        outcome: dict[str, float] = {}

        def naive_alter() -> None:
            with connect(self._settings, application_name="naive-alter") as alter_connection:
                started = time.perf_counter()
                alter_connection.execute("ALTER TABLE events ADD COLUMN flagged boolean")
                outcome["alter_seconds"] = time.perf_counter() - started

        alter_thread = threading.Thread(target=naive_alter, name="naive-alter")
        alter_thread.start()
        try:
            time.sleep(hold_seconds / 2)
            snapshot = snapshot_locks(observer)  # the queue as it stands, mid-pile-up
            time.sleep(hold_seconds / 2)
        finally:
            long_transaction.rollback()
            long_transaction.close()
            alter_thread.join()
            observer.close()
        logger.info("lock queue observed", extra=fields(waiting=len(snapshot.waiting), held_seconds=hold_seconds))
        return QueueOutcome(snapshot, outcome["alter_seconds"])

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

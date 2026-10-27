"""Adapter: the events table as a whole. Implements `LabTable`."""

from __future__ import annotations

from psycopg import errors

from ..domain.errors import LockWaitTimeoutError
from ..domain.outcomes import TableSize
from .postgres import scalar, session
from .retry import retry
from .settings import PostgresSettings

_RESET_STATEMENTS = (
    "DROP INDEX IF EXISTS idx_events_device_created",
    "DROP INDEX IF EXISTS idx_events_naive",
    "ALTER TABLE events DROP CONSTRAINT IF EXISTS flagged_not_null",
    "ALTER TABLE events DROP COLUMN IF EXISTS flagged",
    "ALTER TABLE events DROP COLUMN IF EXISTS scratch",
    "ALTER TABLE events DROP COLUMN IF EXISTS conflict_probe",
    "DROP STATISTICS IF EXISTS events_region_city",
)


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

"""Adapter: the health check of the one dependency, PostgreSQL."""

from __future__ import annotations

import psycopg

from ..application.health import ProbeFailedError
from .postgres import scalar, session
from .settings import PostgresSettings


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

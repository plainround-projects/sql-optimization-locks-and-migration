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

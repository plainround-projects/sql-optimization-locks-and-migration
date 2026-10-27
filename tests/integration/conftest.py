"""Fixtures for the tests that need the seeded database from `make up db`, with the load script running."""

import time
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from locks_lab.application.scenarios import Scenarios
from locks_lab.domain.stats import WindowSummary
from locks_lab.infrastructure import postgres
from locks_lab.infrastructure.lab_table import PostgresLabTable
from locks_lab.infrastructure.load_runner import ThreadedLoad
from locks_lab.infrastructure.lock_experiments import PostgresLockExperiments
from locks_lab.infrastructure.plan_flip import PostgresPlanFlip
from locks_lab.infrastructure.schema_changes import PostgresSchemaChanges
from locks_lab.infrastructure.settings import Settings

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

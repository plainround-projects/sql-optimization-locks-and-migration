"""Startup shared by the programs: settings or a clear exit code 2, and the composition root."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from ..application.scenarios import Scenarios
from ..domain.host import HostLoad
from ..infrastructure.lab_table import PostgresLabTable
from ..infrastructure.lock_experiments import PostgresLockExperiments
from ..infrastructure.logging import configure_logging
from ..infrastructure.plan_flip import PostgresPlanFlip
from ..infrastructure.schema_changes import PostgresSchemaChanges
from ..infrastructure.settings import ConfigurationError, Settings


def load_settings() -> Settings | None:
    """Read and validate the environment, configure logging, or print the problem and return None."""
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return None
    configure_logging(settings.log_level)
    return settings


def measure_host_load() -> HostLoad:
    """The 1-minute load average and CPU count right now, so results can say how busy the machine was."""
    return HostLoad(os.getloadavg()[0], os.cpu_count() or 1)


def build_table(settings: Settings) -> PostgresLabTable:
    """The events table adapter."""
    return PostgresLabTable(settings.postgres)


def build_scenarios(settings: Settings, pause: Callable[[float], None], should_stop: Callable[[], bool]) -> Scenarios:
    """Wire the scenarios to their PostgreSQL adapters: the one place that knows which implementations are in use."""
    return Scenarios(
        table=build_table(settings),
        locks=PostgresLockExperiments(settings.postgres),
        changes=PostgresSchemaChanges(settings.postgres, settings.sql_dir),
        flip=PostgresPlanFlip(settings.postgres, settings.sql_dir),
        pause=pause,
        should_stop=should_stop,
    )

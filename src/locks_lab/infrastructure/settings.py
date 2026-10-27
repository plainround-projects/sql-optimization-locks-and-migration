"""Configuration from the environment, validated once at startup (twelve-factor). Secrets only from here."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_INTERVAL = re.compile(r"^\d+(ms|s|min)$")


class ConfigurationError(ValueError):
    """An environment variable is missing or has an unusable value."""


def _text(environ: Mapping[str, str], name: str, default: str | None = None) -> str:
    value = environ.get(name, default if default is not None else "").strip()
    if not value:
        raise ConfigurationError(f"{name} must be set and not empty (copy .env.example to .env)")
    return value


def _non_negative_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, str(default)).strip()
    if not raw.isdigit():
        raise ConfigurationError(f"{name} must be a non-negative integer, got {raw!r}")
    return int(raw)


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    value = _non_negative_int(environ, name, default)
    if value < 1:
        raise ConfigurationError(f"{name} must be at least 1, got {value}")
    return value


def _positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from error
    if value < 0:
        raise ConfigurationError(f"{name} must not be negative, got {raw!r}")
    return value


@dataclass(frozen=True, slots=True)
class PostgresSettings:
    """The PostgreSQL part of the configuration; the password is never printed."""

    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    connect_timeout_seconds: int
    statement_timeout_ms: int
    max_parallel_workers_per_gather: int


@dataclass(frozen=True, slots=True)
class LoadSettings:
    """The load script: iterations of insert, update and read, spread over a few connections."""

    iterations_per_second: int
    workers: int
    statement_timeout_ms: int


@dataclass(frozen=True, slots=True)
class MigrationSettings:
    """The safe migration's knobs: the backfill batch and pause, and how long a lock may be waited for."""

    batch_size: int
    pause_seconds: float
    lock_timeout: str


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the programs read from the environment. See .env.example for each variable."""

    postgres: PostgresSettings
    load: LoadSettings
    migration: MigrationSettings
    baseline_seconds: int
    closing_seconds: int
    sql_dir: Path
    log_level: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Read and validate the environment; raises `ConfigurationError` naming the first bad variable."""
        env = os.environ if environ is None else environ
        level = _text(env, "LOG_LEVEL", "INFO").upper()
        if level not in _LEVELS:
            raise ConfigurationError(f"LOG_LEVEL must be one of {sorted(_LEVELS)}, got {level!r}")
        lock_timeout = _text(env, "LOCK_TIMEOUT", "2s")
        if not _INTERVAL.match(lock_timeout):
            raise ConfigurationError(f"LOCK_TIMEOUT must look like 500ms, 2s or 1min, got {lock_timeout!r}")
        default_sql = Path(__file__).resolve().parents[3] / "sql"
        return cls(
            postgres=PostgresSettings(
                host=_text(env, "PGHOST", "localhost"),
                port=_positive_int(env, "PGPORT", 55433),
                database=_text(env, "PGDATABASE", "lab"),
                user=_text(env, "PGUSER", "lab"),
                password=_text(env, "PGPASSWORD"),
                connect_timeout_seconds=_positive_int(env, "PG_CONNECT_TIMEOUT_SECONDS", 5),
                statement_timeout_ms=_positive_int(env, "PG_STATEMENT_TIMEOUT_MS", 600_000),
                max_parallel_workers_per_gather=_non_negative_int(env, "PG_PARALLEL_WORKERS_PER_GATHER", 0),
            ),
            load=LoadSettings(
                iterations_per_second=_positive_int(env, "LOAD_ITERATIONS_PER_SECOND", 40),
                workers=_positive_int(env, "LOAD_WORKERS", 4),
                statement_timeout_ms=_positive_int(env, "LOAD_STATEMENT_TIMEOUT_MS", 3000),
            ),
            migration=MigrationSettings(
                batch_size=_positive_int(env, "BACKFILL_BATCH", 2000),
                pause_seconds=_positive_float(env, "BACKFILL_PAUSE_SECONDS", 0.05),
                lock_timeout=lock_timeout,
            ),
            baseline_seconds=_positive_int(env, "BASELINE_SECONDS", 60),
            closing_seconds=_positive_int(env, "CLOSING_SECONDS", 20),
            sql_dir=Path(_text(env, "LAB_SQL_DIR", str(default_sql))),
            log_level=level,
        )

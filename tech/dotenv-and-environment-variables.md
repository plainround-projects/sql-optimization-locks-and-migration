# Environment variables and the .env file

## What it is

An **environment variable** is a named piece of text that the operating system keeps for each running program: `PGPORT=55431`. A program is started with a copy of its parent's variables, and can read them. This is the usual way to give a program its **settings** (a database address, a password, a log level) without writing them into the code. The approach is called **twelve-factor configuration** ("store config in the environment").

A **`.env` file** is a plain text file with one `NAME=value` per line. It is a convenience for a developer's machine: a tool reads the file and puts the lines into the environment of the programs it starts. It must never be committed if it holds secrets; a **`.env.example`** with harmless placeholders is committed instead, and you copy it to `.env`.

## Why this repository uses it

The database address, the user, the password and the timeouts belong to the machine, not to the code. Both the Compose file and the Python programs read the same variables, so there is one place to change a port or a password.

## Where it appears

| File | What it does |
|---|---|
| `.env.example` | The committed list of variables with harmless example values. `make env` copies it to `.env` when there is no `.env`. |
| `.env` | Your local copy. Ignored by git (`.gitignore`) and by Docker builds (`.dockerignore`). |
| `Makefile` | `-include .env` and `export` read the file and pass the variables to every command. |
| `docker-compose.yml` | Uses `${PGUSER:-lab}`, `${PGPASSWORD:?...}`, `${PGDATABASE:-lab}`, `${PGPORT:-55433}`. |
| `Makefile` (also) | `ROWS ?= 2000000` is passed to `psql` as `-v rows=...` for the seed. |
| `src/locks_lab/infrastructure/settings.py` | Reads and validates all variables. |
| `.github/workflows/ci.yml` | Sets the same variables (and `ROWS: "1000000"`) in the job's `env:` block. |
| `Dockerfile` | Sets `LAB_SQL_DIR`; the example `docker run` passes `PGPASSWORD`. |

## How it works underneath

- A process receives its environment as a list of `NAME=value` strings when it starts. A child process gets a copy; changing a variable in the child does not change the parent's.
- In a shell, `NAME=value command` sets a variable for that one command; `export NAME=value` sets it for every later command in that shell.
- In Python, `os.environ` is a dictionary-like view of the environment; `os.environ.get("NAME", "default")` reads one with a fallback. Values are always **text**, even `5432`; the program converts and validates them.
- Two different tools read `.env` here: **Make** includes it as makefile text (`-include .env` plus `export` passes the variables on), and **Docker Compose** reads a `.env` file next to `docker-compose.yml` to fill `${NAME}` placeholders. The Python programs never read the file; they read their environment, which Make filled.
- **Validation at start-up.** A good program checks all its settings once, at the beginning, and stops with one clear message if one is missing or wrong, rather than failing later in the middle of work.
- **No secret defaults.** A password with a default value in the code is a password everyone knows. Here the password has no default: without it the program (and Compose) refuses to start.

## Walkthrough of this repository's use

The variables:

| Variable | Meaning | Default in the code |
|---|---|---|
| `PGHOST` | where PostgreSQL listens | `localhost` |
| `PGPORT` | its port | `55433` |
| `PGDATABASE` | database name | `lab` |
| `PGUSER` | user name | `lab` |
| `PGPASSWORD` | password | none: must be set |
| `PG_CONNECT_TIMEOUT_SECONDS` | how long to wait for a connection | `5` |
| `PG_STATEMENT_TIMEOUT_MS` | longest a statement may run (the migrations, the index build) | `600000` (10 minutes) |
| `PG_PARALLEL_WORKERS_PER_GATHER` | parallel query workers per session | `0` |
| `LOAD_ITERATIONS_PER_SECOND` | iterations (insert, update, read) per second over all workers | `40` |
| `LOAD_WORKERS` | worker threads, one connection each | `4` |
| `LOAD_STATEMENT_TIMEOUT_MS` | longest a load statement may run before it counts as an error | `3000` |
| `BACKFILL_BATCH` | rows per backfill batch | `2000` |
| `BACKFILL_PAUSE_SECONDS` | pause between batches | `0.05` |
| `LOCK_TIMEOUT` | how long a migration may wait for a lock | `2s` |
| `BASELINE_SECONDS` | steady load before the first change | `60` |
| `CLOSING_SECONDS` | closing baseline | `20` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` | `INFO` |
| `LAB_SQL_DIR` | folder with the SQL files | the repository's `sql/` |

`ROWS` (rows to seed) is read by Make and passed to `psql`, not by the Python programs.

### The helper functions

`src/locks_lab/infrastructure/settings.py`, lines 1 to 49:

```python
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

```

- Line 11: `_LEVELS` is a set of the four allowed log levels. Line 12: `_INTERVAL` is a regular expression for a PostgreSQL time such as `2s` (regular-expressions note). `ConfigurationError(ValueError)` is the one error type for bad settings.
- `_text(environ, name, default=None)`: reads the variable from the given mapping (`environ.get(name, default if default is not None else "")`), removes surrounding blanks with `.strip()`, and raises `ConfigurationError` if the result is empty. The message ends with "(copy .env.example to .env)", the fix for a missing password.
- `_non_negative_int`: takes the text (default converted with `str(default)`), checks `raw.isdigit()` (only digits 0 to 9, so no sign or decimal point), raises a clear error showing the bad value with `{raw!r}` (the `!r` shows quotes around text), and returns `int(raw)`.
- `_positive_int`: the same plus "at least 1".
- `_positive_float`: converts with `float(raw)`; `float("abc")` raises `ValueError`, which is caught with `except ValueError as error` and re-raised as a `ConfigurationError` with `from error`; negative numbers are refused (zero is allowed: a pause of 0 seconds).

### The settings classes and `from_env`

`src/locks_lab/infrastructure/settings.py`, lines 51 to 131:

```python
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
```

- `PostgresSettings`, `LoadSettings`, `MigrationSettings` and `Settings` are frozen dataclasses (dataclasses note); the password field is hidden from printing.
- `from_env(cls, environ=None)` is a `@classmethod`: `cls` is the class itself. `env = os.environ if environ is None else environ` lets tests pass their own dictionary instead of the real environment.
- It reads `LOG_LEVEL` (`.upper()` makes `info` valid), checks it is one of the four allowed values, and raises `ConfigurationError` listing them.
- `LOCK_TIMEOUT` is checked against `_INTERVAL`; the value ends up in SQL text, so it must be a plain interval.
- `default_sql = Path(__file__).resolve().parents[3] / "sql"` computes the default SQL folder: `__file__` is `.../src/locks_lab/infrastructure/settings.py`; `.resolve()` makes it absolute; `.parents[3]` goes up three levels (infrastructure, locks_lab, src) to the repository root; `/ "sql"` appends `sql`. In the Docker image `LAB_SQL_DIR=/app/sql` overrides it.
- Each setting is read with its function and default; `600_000` (underscores in numbers are only for readability).
- `password=_text(env, "PGPASSWORD")` has no default, so a missing or empty password raises the error and the command exits with code 2.

### How the values reach the program

`Makefile`, lines 7 to 13:

```make
-include .env
export
PGHOST ?= localhost
PGPORT ?= 55433
PGUSER ?= lab
PGDATABASE ?= lab
ROWS ?= 2000000
```

`-include .env` makes Make read `PGPASSWORD=...` lines; `export` hands every Make variable to the commands it starts; the `?=` lines add defaults for the connection variables and `ROWS`. So `make run` starts `locks-lab-run` with a complete environment. When you run a program yourself, load the file first: `set -a; . ./.env; set +a` (`set -a` exports every variable assigned afterwards; `.` reads the file as shell commands).

## Try it yourself

1. `make env` — prints `created .env from .env.example` the first time and nothing afterwards.
2. `PGPASSWORD= .venv/bin/locks-lab-health; echo "exit=$?"` — the configuration error and exit code 2.
3. `PGPORT=abc .venv/bin/locks-lab-health` (with the other variables loaded) — `configuration error: PGPORT must be a non-negative integer, got 'abc'`.
4. `BACKFILL_PAUSE_SECONDS=-1 .venv/bin/locks-lab-health` (same) — `configuration error: BACKFILL_PAUSE_SECONDS must not be negative, got '-1'`.
5. `.venv/bin/python -c "from locks_lab.infrastructure.settings import Settings; print(Settings.from_env({'PGPASSWORD': 'x'}))"` — prints the whole settings object with defaults and no password.
6. `docker compose config | grep POSTGRES_` — shows Compose's view of the three `POSTGRES_*` values after substitution.

## Mistakes people make

- Committing a `.env` with real passwords.
- Putting a default password in code "for convenience".
- Forgetting that all values are text (`"0"` is a true value in an `if` check, while the integer `0` is false).
- Spaces around `=` in a `.env` file (`NAME = value` is not the same as `NAME=value`).
- Assuming a variable set in one terminal exists in another.

**How this repository avoids them.** No secret has a default value. `.env` is ignored by git and by Docker. Every number is validated at start-up and the message names the variable. Tests pass a dictionary instead of touching the real environment.

## Check yourself

1. Why are settings read from the environment and not from code? *The same code can run in different places with different settings, and secrets never enter the repository.*
2. Is `PGPORT=55431` a number or text when the program reads it? *Text; the program must convert it.*
3. What does a `.env.example` file contain? *Placeholder values for every variable, committed to show which ones exist; the real `.env` is not committed.*
4. What does `NAME=value command` do in a shell? *Runs the command with `NAME` set to `value` for that command only.*
5. Why check all settings at start-up? *So a wrong or missing value produces one clear error right away, not a failure halfway through the work.*

## Further reading

- The Twelve-Factor App, "III. Config": https://12factor.net/config
- Python `os.environ`: https://docs.python.org/3.13/library/os.html#os.environ
- Compose `.env` files and interpolation: https://docs.docker.com/compose/how-tos/environment-variables/

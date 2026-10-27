# Logging and logfmt

## What it is

**Logging** means a program writing short lines about what it is doing (starting, retrying, failing) to a place where a person or another program can read them later. Python's standard module `logging` handles the plumbing: you write `logger.info("message")`, and configuration decides where the line goes and what it looks like. **logfmt** is a simple line format of `key=value` pairs separated by spaces, easy for humans to read and for tools to search.

## Why this repository uses it

A replay takes minutes and talks to a database. When something goes wrong (a refused connection, a retry, an interrupted step) the person running it needs lines that say what happened and when, without opening the code. The rule "structured logging" of the quality bar is met by one small module.

## Where it appears

| File | What it does |
|---|---|
| `infrastructure/logging.py` | The formatter and the set-up function. |
| `interfaces/common.py` | Calls `configure_logging(settings.log_level)` at start-up. |
| `infrastructure/postgres.py` | Logs each connection retry as a warning. |
| `infrastructure/schema_changes.py` | Logs each migration that had to wait for a lock and try again. |
| `infrastructure/lock_experiments.py` | Logs the lock queue it observed. |
| `infrastructure/load_runner.py` | Logs each second of the load at `DEBUG` level. |
| `interfaces/run_cli.py` | Logs progress, an interruption and a failed lesson. |
| `infrastructure/settings.py` | Reads `LOG_LEVEL`. |

## How it works underneath

**Parts of the `logging` module.**

- A **logger** is a named object you get with `logging.getLogger(__name__)`; `__name__` is the module's dotted name, so each module has its own logger and the names form a tree (`slow_queries.infrastructure.postgres` is below `slow_queries`).
- A **log record** is the data of one event: the level, the message, the time, the logger name and any extra fields.
- **Levels** from least to most serious: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. The root logger has a level; records below it are dropped.
- A **handler** sends records somewhere: `StreamHandler` writes to a stream (standard error here), `FileHandler` to a file.
- A **formatter** turns a record into the text line.
- Records pass up the tree to the **root logger**, whose handlers do the output. `logging.getLogger()` with no name is the root.
- `logger.info("text", extra={"fields": {...}})`: the `extra` dictionary adds attributes to the record, so a formatter can print them.

**Why standard error.** Programs print results on **standard output** and logs on **standard error**, so `program > results.txt` captures only the results and logs stay visible.

**Structured logging** means the lines have a fixed shape, so machines can parse them: `ts=2026-10-27T12:00:00.123+00:00 level=INFO logger=x msg="applied migration" number=1`. Values with spaces or quotes are put in double quotes (here with `json.dumps`).

**Do not log secrets.** A log is copied around; a password must never be in it.

## Walkthrough of this repository's use

`src/locks_lab/infrastructure/logging.py`, lines 1 to 45:

```python
"""Structured logging: one logfmt line per event (`ts=... level=... logger=... msg=... key=value`)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, TextIO


def _quote(value: object) -> str:
    text = str(value)
    return json.dumps(text) if not text or any(char in text for char in ' ="\n') else text


class LogfmtFormatter(logging.Formatter):
    """Format a log record as one logfmt line, with the record's extra fields as key=value pairs."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds")
        parts = [
            f"ts={timestamp}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"msg={_quote(record.getMessage())}",
        ]
        parts.extend(f"{key}={_quote(value)}" for key, value in getattr(record, "fields", {}).items())
        if record.exc_info:
            parts.append(f"exc={_quote(self.formatException(record.exc_info))}")
        return " ".join(parts)


def fields(**values: Any) -> dict[str, Any]:
    """Use as `logger.info("message", extra=fields(order_id=...))` to attach key=value pairs."""
    return {"fields": values}


def configure_logging(level: str, stream: TextIO | None = None) -> None:
    """Send every log record to `stream` (stderr by default) as logfmt. Safe to call twice."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(LogfmtFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
```

- Line 1: the docstring shows the output shape. Lines 5 to 9 import `json` (to quote values), `logging`, `sys`, `datetime` with `UTC`, and the types `Any` and `TextIO`.
- `_quote(value)` (lines 12 to 14): turns the value into text; if the text is empty or contains a space, an equals sign, a double quote or a line break (`any(char in text for char in ' ="\n')`), it returns the JSON-quoted form (`json.dumps(text)` gives `"two words"` with escapes), otherwise the text as is.
- `class LogfmtFormatter(logging.Formatter)` (lines 17 to 31) inherits from the standard formatter and overrides `format`, which receives the record and returns the line.
  - `datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds")` converts the record's creation time to a UTC time stamp with milliseconds.
  - The list `parts` holds `ts=...`, `level=...`, `logger=...`, `msg=...` (the message, quoted if needed; `record.getMessage()` is the message text).
  - `getattr(record, "fields", {})` reads the extra fields if the record has them, otherwise an empty dictionary. `parts.extend(...)` adds a `key=value` pair for each.
  - `if record.exc_info:` adds `exc=...` with the formatted traceback when the call was made while handling an error.
  - `" ".join(parts)` makes the line.
- `fields(**values)` (lines 34 to 36): `**values` collects keyword arguments into a dictionary; the function returns `{"fields": values}` so it can be passed as `extra=`. Use: `logger.info("applied migration", extra=fields(number=1, file="001_index_created_at.sql"))`.
- `configure_logging(level, stream=None)` (lines 39 to 45): builds a `StreamHandler` on the given stream or `sys.stderr` (`stream or sys.stderr`), sets the formatter, gets the root logger, replaces its handler list with just this one (`root.handlers[:] = [handler]`, which is why calling it twice is safe) and sets the level, a text such as `"INFO"`.

How a module logs:

`src/locks_lab/infrastructure/schema_changes.py`, lines 31 to 31:

```python
logger = logging.getLogger(__name__)
```
`src/locks_lab/infrastructure/schema_changes.py`, lines 73 to 75:

```python
                on_retry=lambda n, _error: logger.warning(
                    "lock_timeout, retrying", extra=fields(migration=number, attempt=n)
                ),
```

`logger = logging.getLogger(__name__)` is at the top of each module that logs. `logger.warning("lock_timeout, retrying", extra=fields(migration=number, attempt=n))` produces a line like `ts=2026-10-27T12:00:00.123+00:00 level=WARNING logger=locks_lab.infrastructure.schema_changes msg="lock_timeout, retrying" migration=1 attempt=1`: the migration waited 2 s for its lock, gave up (that is the lock timeout working), and will try again. In `load_runner.py` line 174 the reporter logs `logger.debug("load tick", extra=fields(ops=..., errors=..., p99_ms=...))` once a second; `DEBUG` lines appear only with `LOG_LEVEL=DEBUG`.

`src/locks_lab/infrastructure/postgres.py`, lines 54 to 56:

```python
        on_retry=lambda attempt, error: logger.warning(
            "retrying database connection", extra=fields(attempt=attempt, error=error)
        ),
```

The retry callback logs a `WARNING` with the attempt number and the error each time a connection attempt fails.

## Try it yourself

1. `.venv/bin/python -c "import logging; from locks_lab.infrastructure.logging import configure_logging, fields; configure_logging('INFO'); logging.getLogger('demo').info('two words', extra=fields(n=1, text='a b'))"` prints one line to standard error such as `ts=2026-10-27T12:00:00.123+00:00 level=INFO logger=demo msg="two words" n=1 text="a b"`.
2. Run the same with `'WARNING'` instead of `'INFO'`: nothing is printed, because the level filters it out.
3. `LOG_LEVEL=LOUD make health` (with your `.env` loaded by Make) prints `configuration error: LOG_LEVEL must be one of ['DEBUG', 'ERROR', 'INFO', 'WARNING'], got 'LOUD'` and fails with exit code 2: the level is validated at start-up.
4. `.venv/bin/locks-lab-health 2>/dev/null` hides the logs (standard error goes to `/dev/null`) and shows only the result line.

## Mistakes people make

- Calling `print` for diagnostics: it cannot be filtered by level.
- Building the message with an f-string before the level check, which costs time for dropped messages (here the messages are short and fixed).
- Logging secrets or whole request bodies.
- Configuring logging in a library module instead of in the program's start-up code.
- Adding a handler twice and getting every line twice.

**How this repository avoids them.** Logs go to standard error, results to standard output. The password is never passed to a log call (the connection retry logs the attempt number and the error that psycopg raised). Logging is configured once in `interfaces/common.py`, not in library modules. `configure_logging` replaces the handler list, so there are no doubled lines.

## Check yourself

1. What is `logging.getLogger(__name__)`? *A logger named after the current module, so lines can be traced to their source and filtered by module.*
2. Where do log lines go in this repository? *Standard error, as logfmt lines.*
3. What does a handler do, and what does a formatter do? *The handler sends the record to a destination; the formatter turns it into text.*
4. What is the difference between `INFO` and `WARNING`? *`INFO` reports normal progress; `WARNING` reports something unexpected that was handled.*
5. Why use `key=value` instead of free text? *Tools can search and filter by key without guessing the sentence.*

## Further reading

- `logging` module (3.13): https://docs.python.org/3.13/library/logging.html and Logging HOWTO: https://docs.python.org/3.13/howto/logging.html
- The logfmt convention: https://brandur.org/logfmt

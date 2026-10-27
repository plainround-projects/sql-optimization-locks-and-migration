# The Python standard library

## What it is

The **standard library** is the set of modules that come with Python itself, with nothing to install. You load one with `import`. This note covers the modules this repository uses for files, time, randomness, statistics and JSON. (Logging, command-line parsing, signals and regular expressions have notes of their own.)

## Why this repository uses it

The only third-party package at run time is `psycopg`. Files, retries, percentiles, JSON lines, time and dictionaries all come from the standard library, which keeps the lock file to four lines.

## Where it appears

| File | Modules |
|---|---|
| `infrastructure/artifacts.py` | `pathlib` |
| `infrastructure/retry.py` | `random`, `time` |
| `infrastructure/sql_script.py` | `pathlib`, `re`, text methods |
| `infrastructure/settings.py` | `os`, `pathlib`, `re` (environment note) |
| `infrastructure/postgres.py` | `contextlib` |
| `infrastructure/load_runner.py` | `collections.deque`, `json`, `random`, `time`, `pathlib` (threads note for `threading`) |
| `domain/stats.py` | `math`, `sorted` |
| `domain/backfill.py` | a generator |
| `interfaces/common.py` | `os.getloadavg`, `os.cpu_count` |
| `interfaces/load_cli.py` | `dataclasses.asdict`, `json`, `time` |
| `infrastructure/logging.py` | `json`, `datetime` (logging note) |
| `tests/` | `subprocess`, `os`, `sys`, `pathlib`, `dataclasses`, `threading` |

## How it works underneath

**`pathlib`.** A `Path` object stands for a file or folder path. `Path("a") / "b.txt"` joins parts with the right separator (`a/b.txt`). Useful members: `.name` (last part), `.parent`, `.parents[i]` (ancestors), `.resolve()` (make absolute, follow links), `.exists()`, `.read_text()` (whole file as text), `.write_text(text)`, `.mkdir(parents=True, exist_ok=True)` (create the folder and missing parents, no error if it exists), `.glob("*.sql")` (files matching a pattern), `__file__` (the path of the current module).

**`os`.** `os.environ` is the dictionary of environment variables. `os.getloadavg()` returns the system's load averages over 1, 5 and 15 minutes (a measure of how many programs were waiting to run). `os.cpu_count()` returns the number of CPUs or `None`.

**`sys`.** `sys.stderr` is the standard error stream; `sys.executable` is the path of the running Python; `sys.argv` the command-line words.

**`time`.** `time.sleep(seconds)` pauses the program. `time.perf_counter()` is a clock for measuring durations.

**`random`.** `random.Random()` makes a random-number generator object; `.uniform(a, b)` returns a random decimal between `a` and `b`. Passing a fixed seed makes the numbers repeatable, which tests rely on.

**`statistics`.** `statistics.median(numbers)` is the middle value of the sorted numbers (the average of the two middle ones if there is an even count).

**`json`.** `json.dumps(value)` turns a Python value into JSON text (text with quotes, braces and brackets); `json.loads(text)` does the opposite.

**`datetime`.** `datetime.fromtimestamp(seconds, tz=UTC)` converts a Unix timestamp (seconds since 1970-01-01 00:00 UTC) to a date-time object in a stated time zone; `.isoformat(timespec="milliseconds")` prints it as `2026-10-27T12:00:00.123+00:00`.

**`contextlib.contextmanager`.** Turns a generator function with one `yield` into a context manager usable with `with`: code before `yield` is the set-up, the yielded value is what `as name` receives, and code after it (in `finally`) is the clean-up.

**`collections.abc`**, **`typing`** and **`dataclasses`**: see the typing and dataclasses notes.

## Walkthrough of this repository's use

### `infrastructure/artifacts.py`

`src/locks_lab/infrastructure/artifacts.py`, lines 1 to 23:

```python
"""Adapter: the replay's evidence as files next to the queries. Implements `ArtifactStore`."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class FileArtifactStore:
    """Writes `<name>.txt` plans, named text captures and `results.md` into one directory."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        self.save_text(f"{name}.txt", "\n".join(lines) + "\n")

    def save_text(self, name: str, text: str) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        (self._directory / name).write_text(text)

    def save_report(self, text: str) -> None:
        self.save_text("results.md", text)
```

`FileArtifactStore` keeps one folder (`self._directory`, a `Path`). `save_text(name, text)` first makes sure the folder exists (`mkdir(parents=True, exist_ok=True)`), then writes the text to `self._directory / name` (the `/` operator joins a folder and a file name) with `.write_text(text)`. `save_plan(name, lines)` joins the lines with line breaks and a final one (`"\n".join(lines) + "\n"`) and delegates to `save_text(f"{name}.txt", ...)`; `save_report(text)` delegates with the name `results.md`. The class has the three methods and types of the `ArtifactStore` port, so it satisfies it (typing note).

### `infrastructure/retry.py`

`src/locks_lab/infrastructure/retry.py`, lines 1 to 38:

```python
"""Retry with exponential backoff and jitter for calls that cross the network."""

from __future__ import annotations

import random
import time
from collections.abc import Callable


def retry[T](
    operation: Callable[[], T],
    *,
    attempts: int,
    base_delay_seconds: float,
    retry_on: tuple[type[BaseException], ...],
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    max_delay_seconds: float = 10.0,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Call `operation` up to `attempts` times, doubling the pause after each failure in `retry_on`.

    The pause is `base * 2**(attempt - 1)` capped at `max_delay_seconds`, then scaled by a random
    factor in [0.5, 1.0] so many clients do not retry in step. The last failure is raised.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    jitter = rng or random.Random()
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except retry_on as error:
            if attempt == attempts:
                raise
            if on_retry:
                on_retry(attempt, error)
            sleep(min(max_delay_seconds, base_delay_seconds * 2 ** (attempt - 1)) * jitter.uniform(0.5, 1.0))
    raise AssertionError("unreachable")  # pragma: no cover
```

- Imports: `random` and `time`, and `Callable` for types.
- Line 26: `if attempts < 1: raise ValueError(...)` refuses a nonsense argument.
- Line 28: `jitter = rng or random.Random()` uses the given generator or makes a new one (`or` returns the right side if the left is `None`).
- Line 29: `for attempt in range(1, attempts + 1):` counts 1, 2, ... up to `attempts`.
- Lines 30 to 37: try the operation; `return operation()` ends the function at the first success. `except retry_on as error:` catches only the error classes given. On the last attempt (`attempt == attempts`) a bare `raise` re-raises the same error. Otherwise it calls `on_retry` if given and sleeps.
- The pause is `min(max_delay_seconds, base_delay_seconds * 2 ** (attempt - 1)) * jitter.uniform(0.5, 1.0)`: `**` is "to the power of", so with a base of 0.5 s the delays are 0.5, 1, 2, 4... seconds, capped at `max_delay_seconds` (10 s), then multiplied by a random number between 0.5 and 1.0. This is **exponential backoff with jitter**: wait longer after each failure, and add randomness so that many clients do not all retry at the same instant.
- Line 38: `raise AssertionError("unreachable")  # pragma: no cover` documents that the loop always returns or raises; the comment tells the coverage tool to ignore the line.

### `infrastructure/sql_script.py`

`src/locks_lab/infrastructure/sql_script.py`, lines 1 to 68:

```python
"""Read the repository's SQL files and run them statement by statement."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import psycopg

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_]*\$")


def split_statements(sql_text: str) -> list[str]:
    """Split SQL on semicolons, ignoring `--` comments, quoted text and `$$ ... $$` bodies.

    psql meta-commands (lines starting with a backslash) are not SQL and are dropped.
    """
    lines = [line.split("--", 1)[0] for line in sql_text.splitlines() if not line.lstrip().startswith("\\")]
    text = "\n".join(lines)
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    dollar: str | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if dollar:
            if text.startswith(dollar, index):
                current.append(dollar)
                index += len(dollar)
                dollar = None
                continue
        elif quote:
            quote = None if character == quote else quote
        elif character in ("'", '"'):
            quote = character
        elif character == "$" and (tag := _DOLLAR_TAG.match(text, index)):
            dollar = tag.group(0)
            current.append(dollar)
            index += len(dollar)
            continue
        elif character == ";":
            statements.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(character)
        index += 1
    return [statement for statement in statements if statement]


def run_file(connection: psycopg.Connection[Any], path: Path, params: Mapping[str, int] | None = None) -> list[Any]:
    """Run every statement of a file on one connection; return the rows of the last one that returns rows.

    The files use psql's `:name` variables; `params` fills them (as `%(name)s`) when the caller runs the file.
    """
    text = path.read_text()
    for name in params or {}:
        text = text.replace(f":{name}", f"%({name})s")
    rows: list[Any] = []
    for statement in split_statements(text):
        uses_params = params is not None and "%(" in statement
        cursor = connection.execute(statement, params) if uses_params else connection.execute(statement)
        if cursor.description:
            rows = cursor.fetchall()
    return rows
```

This is the module that lets Python run the repository's `.sql` files.

- `split_statements(sql_text)` turns the text of a file into separate statements. Line 20: `lines = [line.split("--", 1)[0] for line in sql_text.splitlines() if not line.lstrip().startswith("\\")]` is a list comprehension: `splitlines()` splits into lines; lines whose first non-blank character is a backslash are psql meta-commands (not SQL) and are skipped; `line.split("--", 1)[0]` cuts each line at the first `--` (an SQL comment) and keeps the part before it.
- Lines 22 to 50 are a small state machine over the characters of the text. `quote` is `None` outside quotes or holds the quote character that opened the current quoted text; `dollar` is `None` or holds the current dollar-quote marker such as `$$` or `$sql$` (PostgreSQL's way of writing a body that may contain semicolons, as in `DO $$ ... $$;`). `index` is the position in the text. The loop `while index < len(text):` looks at one character at a time.
  - Inside a dollar-quoted body (`if dollar:`), when the text at this position starts with the same marker (`text.startswith(dollar, index)`), the marker is added and the body ends. Other characters are added to `current` at the end of the loop.
  - Inside ordinary quotes (`elif quote:`), the quote closes when the same character comes (`quote = None if character == quote else quote`).
  - A quote character opens a quote; a `$` that starts a marker (`elif character == "$" and (tag := _DOLLAR_TAG.match(text, index))`) opens a dollar-quote. `:=` is the **walrus operator**: it assigns the result of the match to `tag` *and* uses it as the condition in one expression.
  - A `;` outside any quote ends the statement: the collected characters are joined, stripped and saved, and `continue` skips adding the semicolon.
  - Every other character is added to `current`.
  - The last line keeps only non-empty statements.
- `run_file(connection, path, params=None)`: the SQL files written for psql contain `:first_id`-style variables. `text.replace(f":{name}", f"%({name})s")` rewrites each into psycopg's named placeholder `%(first_id)s`, and `connection.execute(statement, params)` sends the values separately (psycopg note). `uses_params = params is not None and "%(" in statement` passes the parameters only to statements that use them (psycopg refuses parameters a statement does not use). `cursor.description` is `None` for statements that return no rows, so `if cursor.description:` tests "this statement returns rows", and then `fetchall()` collects them. The function returns the rows of the last statement that returned rows.

### `math` and sorting in `domain/stats.py`

(Python note.) `math.ceil(x)` rounds up to the next whole number; `sorted(values)` returns a sorted copy; `max(..., default=0.0)` takes the largest item or the default for an empty sequence.

### `collections.deque` and `json` in `infrastructure/load_runner.py`

`src/locks_lab/infrastructure/load_runner.py`, lines 50 to 50:

```python
        self._recent_ids: collections.deque[int] = collections.deque(maxlen=5000)
```
`src/locks_lab/infrastructure/load_runner.py`, lines 185 to 188:

```python
    def _append_metrics(self, entry: dict[str, object]) -> None:
        if self._metrics_path:
            with self._metrics_path.open("a") as handle:
                handle.write(json.dumps(entry) + "\n")
```

`collections.deque(maxlen=5000)` is a **double-ended queue** with a size limit: appending to a full one drops the oldest item. The load keeps the ids of the 5,000 most recently inserted rows in it, so the update statements can pick a recent row with `random.choice(self._recent_ids)`. `_append_metrics` writes one JSON object per line to `load-metrics.jsonl` (the JSON note): `self._metrics_path.open("a")` opens the file for **appending** (`"a"`), so earlier lines stay, `json.dumps(entry) + "\n"` makes the line, and the `with` block closes the file.

### `dataclasses.asdict` in `interfaces/load_cli.py`

`json.dumps(dataclasses.asdict(load.summary(start, load.now())), indent=2)` converts the frozen `WindowSummary` into a dictionary and prints it as indented JSON.

### `contextlib` in `infrastructure/postgres.py`

`src/locks_lab/infrastructure/postgres.py`, lines 60 to 77:

```python
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
```

`session` is a generator with one `yield`, decorated with `@contextmanager`. With `with session(settings) as connection:` the code before `yield` opens a connection, the yielded value becomes `connection`, and the `finally` block closes it even when the body raises. `scalar` returns the first column of the first row of a query, or raises `LookupError` if there is no row.

## Try it yourself

1. `.venv/bin/python -c "from locks_lab.infrastructure.sql_script import split_statements as s; print(s('SELECT 1; -- c\nSELECT 2;'))"` prints `['SELECT 1', 'SELECT 2']`.
2. `.venv/bin/python -c "from locks_lab.infrastructure.sql_script import split_statements as s; print(s(\"SELECT 'a;b';\n\\\\gset\"))"` keeps the semicolon inside the quotes and drops the backslash command: it prints `["SELECT 'a;b'"]`.
3. A dollar-quoted body keeps its semicolons: `.venv/bin/python -c "from locks_lab.infrastructure.sql_script import split_statements as s; print(s('DO \$\$ BEGIN PERFORM 1; END \$\$; SELECT 2;'))"` prints `['DO $$ BEGIN PERFORM 1; END $$', 'SELECT 2']`.
4. `.venv/bin/python -c "import collections; d = collections.deque(maxlen=3); [d.append(i) for i in range(5)]; print(d)"` prints `deque([2, 3, 4], maxlen=3)`: the oldest items were dropped.
5. `.venv/bin/python -c "import math; print(math.ceil(0.99 * 100) - 1, math.ceil(2.1))"` prints `98 3`: the index used for p99 of 100 values, and rounding up.
6. `.venv/bin/python -c "import os; print(os.getloadavg(), os.cpu_count())"` prints three load numbers and the CPU count.

## Mistakes people make

- Building paths by joining strings with `/` (use `Path`).
- Forgetting `exist_ok=True` and getting an error when the folder is already there.
- Using `time.sleep` in a loop with a fixed delay when many clients retry together (use jitter).
- Using `random` for secrets (it is not secure; use `secrets`).
- Using `time.time()` to measure durations (it can jump; use `perf_counter`).

**How this repository avoids them.** Paths are always `Path` objects. Retries have jitter and a cap. Time is slept through an injectable function, so the unit tests do not wait. Files are written with `exist_ok=True`. Medians use the library function.

## Check yourself

1. What does `Path("a") / "b.txt"` give? *The path `a/b.txt` with the right separator for the operating system.*
2. What does `mkdir(parents=True, exist_ok=True)` do? *Creates the folder and any missing parents, and does nothing if it already exists.*
3. What does `statistics.median([1, 9, 3])` return? *3, the middle value after sorting (1, 3, 9).*
4. What does `os.cpu_count() or 1` give if the count is unknown? *1: `or` returns the right side when the left is `None`.*
5. What is a context manager for? *Guaranteeing set-up and clean-up around a block with `with`, also when an error happens.*

## Further reading

- Python Standard Library index (3.13): https://docs.python.org/3.13/library/index.html (`pathlib`, `os`, `time`, `random`, `statistics`, `json`, `datetime`, `contextlib`).

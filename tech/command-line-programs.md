# Command-line programs, exit codes and signals

## What it is

A **command-line program** is started by typing its name and some words (**arguments**) in a terminal. It reads its settings from those arguments and from **environment variables**, prints results, and ends with an **exit code**. This note explains the mechanics that make the programs in this repository behave well: argument parsing, exit codes, standard streams, and **signals** (messages that the operating system or another program sends to a running process).

## Why this repository uses it

The lab is three programs: the replay of the whole lesson (`locks-lab-run`), the load script on its own (`locks-lab-load`) and a health check (`locks-lab-health`). Their exit codes are their contract with `make`, with Docker's `HEALTHCHECK` and with the tests; the replay and the load must stop cleanly on Ctrl-C because they hold database connections and leave a table in a changed state.

## Where it appears

| File | Role |
|---|---|
| `interfaces/health_cli.py` | The health command. |
| `interfaces/run_cli.py` | The replay command, with `argparse`. |
| `interfaces/load_cli.py` | The load command, with `argparse`. |
| `interfaces/common.py` | Shared start-up that returns `None` on bad configuration. |
| `infrastructure/shutdown.py` | The signal flag. |
| `pyproject.toml` | `[project.scripts]` names the three commands. |
| `Dockerfile` | `HEALTHCHECK` and `CMD` use the health command. |

## How it works underneath

**A process** is one running copy of a program. It has a number (the **PID**), three standard streams (input, output, error) and an exit code when it ends.

**Arguments.** The words after the program name arrive as a list of text (`sys.argv`). The standard module `argparse` turns them into named values: `parser.add_argument("--repetitions", type=int, default=5)` declares an optional argument `--repetitions N` whose text is converted to an int; `parser.parse_args(argv)` returns an object with the values, prints a usage message and exits with code 2 if something is wrong, and handles `--help` by itself.

**Exit codes.** The number a process returns to its parent: 0 means success, anything else means a problem. By common convention: 1 is a general failure, 2 is a usage or configuration error, and `128 + N` means "killed by signal N" (130 is `128 + 2`, the usual code after Ctrl-C). In Python, `sys.exit(n)` or `raise SystemExit(n)` ends the program with code `n`. A script uses `raise SystemExit(main())` so the number that `main` returns becomes the exit code.

**Where the program is started.** `python -m package.module` runs a module as the main program. A `[project.scripts]` entry creates a launcher that calls a function and exits with its result.

**Standard output and standard error.** Results go to standard output, diagnostics to standard error. A caller can capture one without the other.

**Signals.** The operating system can send a process a signal. `SIGINT` (number 2) is sent when you press Ctrl-C. `SIGTERM` (15) is the polite "please stop" that `docker stop` and process managers send. By default both kill the process at once. A program can install a **handler**, a function that runs instead: `signal.signal(signal.SIGTERM, handler)`. A handler should do very little; the common pattern is to set a **flag** that the main work checks between steps, so the program can finish the current step, release resources and exit cleanly. `threading.Event` is a thread-safe flag: `.set()` raises it, `.is_set()` reads it.

**Why graceful shutdown matters.** A program killed in the middle of an operation can leave half-done work behind. Stopping between two steps leaves a clear state.

## Walkthrough of this repository's use

### The health command

`src/locks_lab/interfaces/health_cli.py`, lines 1 to 27:

```python
"""Health command: exit 0 when PostgreSQL holds the seeded events table.

python -m locks_lab.interfaces.health_cli
"""

from __future__ import annotations

from collections.abc import Sequence

from ..application.health import check_health
from ..infrastructure.health_probes import PostgresEventsProbe
from .common import load_settings


def main(_argv: Sequence[str] | None = None) -> int:
    """Check PostgreSQL; returns 0 when healthy, 1 when not, 2 when the configuration is unusable."""
    settings = load_settings()
    if settings is None:
        return 2
    report = check_health([PostgresEventsProbe(settings.postgres)])
    for result in report.results:
        print(f"{'ok' if result.ok else 'FAIL'} {result.name}: {result.detail}")
    return 0 if report.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- Lines 1 to 4: the docstring shows how to run it by hand: `python -m locks_lab.interfaces.health_cli`.
- `main(_argv=None) -> int`: the command takes no arguments (the underscore says the parameter is unused). It returns an integer exit code: `2` if the settings are unusable, `0` if healthy, `1` if not.
- `load_settings()` returns `None` after printing `configuration error: ...` (for example, if `PGPASSWORD` is not set).
- `check_health([PostgresEventsProbe(settings.postgres)])` runs the probe; the loop prints one line per result: `ok postgres: 2,000,000 events` or `FAIL postgres: ...`. The expression `'ok' if result.ok else 'FAIL'` picks the word.
- Lines 26 and 27: `if __name__ == "__main__": raise SystemExit(main())` — run as a program, the exit code is what `main` returned.

### The replay command

`src/locks_lab/interfaces/run_cli.py`, lines 1 to 69:

```python
"""Replay the lesson with the load running throughout; writes results.md, the lock queue and the plans.

python -m locks_lab.interfaces.run_cli [--baseline-seconds N] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Sequence
from pathlib import Path

from ..application.replay import ReplayLesson
from ..domain.errors import LabError, LessonInterruptedError
from ..infrastructure.artifacts import FileArtifactStore
from ..infrastructure.load_runner import ThreadedLoad
from ..infrastructure.logging import fields
from ..infrastructure.shutdown import ShutdownSignal
from .common import build_scenarios, build_table, load_settings, measure_host_load

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the replay. Exit codes: 0 done, 1 lab error, 2 bad configuration, 130 interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-seconds", type=int, help="steady load before the first change (default BASELINE_SECONDS)"
    )
    parser.add_argument("--output-dir", type=Path, help="where the notes and plans go (default: sql/explain)")
    arguments = parser.parse_args(argv)
    settings = load_settings()
    if settings is None:
        return 2
    shutdown = ShutdownSignal()
    shutdown.install()
    baseline = arguments.baseline_seconds or settings.baseline_seconds
    metrics = Path("load-metrics.jsonl")
    try:
        with ThreadedLoad(settings.postgres, settings.load, metrics_path=metrics) as load:
            replay = ReplayLesson(
                load=load,
                table=build_table(settings),
                scenarios=build_scenarios(settings, time.sleep, lambda: shutdown.requested),
                store=FileArtifactStore(arguments.output_dir or settings.sql_dir / "explain"),
                baseline_seconds=baseline,
                closing_seconds=settings.closing_seconds,
                batch_size=settings.migration.batch_size,
                pause_seconds=settings.migration.pause_seconds,
                host_load=measure_host_load(),
                progress=lambda message: logger.info(message),
                should_stop=lambda: shutdown.requested,
            )
            result = replay.run()
    except LessonInterruptedError:
        logger.warning("interrupted; the table is left mid-lesson, the next run resets it first")
        return 130
    except LabError as error:
        logger.error("the lesson failed", extra=fields(error=error))
        return 1
    verdict = "within" if result.bar.allows(result.safe.summary) else "not within"
    safe_p99, baseline_p99 = result.safe.summary.p99_ms, result.bar.baseline_p99_ms
    print(f"safe migration p99 {safe_p99} ms: {verdict} twice the baseline ({baseline_p99} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- `argparse.ArgumentParser(description=__doc__)` makes the parser and uses the module's docstring as the help text. `--baseline-seconds` (an integer, default `None`) and `--output-dir` (converted to a `Path`). `baseline = arguments.baseline_seconds or settings.baseline_seconds` uses the option if given, otherwise `BASELINE_SECONDS`.
- `settings = load_settings()`; `if settings is None: return 2`. `shutdown = ShutdownSignal(); shutdown.install()` installs the signal handlers (below).
- `metrics = Path("load-metrics.jsonl")` is the per-second record, written in the current folder.
- `with ThreadedLoad(settings.postgres, settings.load, metrics_path=metrics) as load:` starts the load threads and guarantees they are stopped when the block ends, even on an error or an interrupt (threads note). Inside, `ReplayLesson(...)` is created with everything passed by keyword: the load, the table adapter (`build_table`), the scenarios (`build_scenarios(settings, time.sleep, lambda: shutdown.requested)`: the pause function is the real `time.sleep` and the stop test is a lambda reading the flag), the artifact store (the folder `sql/explain` by default), the baseline length, the closing baseline, the backfill batch size and pause, the machine load, a progress function (`lambda message: logger.info(message)`) and the stop test. `result = replay.run()`.
- `except LessonInterruptedError:` a signal arrived: log a warning (the table is left mid-lesson; the next run resets it first) and return `130`. `except LabError as error:` log the failure and return `1`. Anything else would be a bug and would show a traceback with exit code 1.
- After a successful run it prints one line to **standard output**: `verdict = "within" if result.bar.allows(result.safe.summary) else "not within"` then `print(f"safe migration p99 {safe_p99} ms: {verdict} twice the baseline ({baseline_p99} ms)")`. It returns `0`: the exit code means "the replay completed", not "the bar was met" (the verdict is the printed line and the results file).

### The load command

`src/locks_lab/interfaces/load_cli.py`, lines 1 to 41:

```python
"""The lesson's load script on its own: steady inserts, updates and reads, one line per second.

python -m locks_lab.interfaces.load_cli --seconds 60
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from collections.abc import Sequence

from ..infrastructure.load_runner import ThreadedLoad
from ..infrastructure.shutdown import ShutdownSignal
from .common import load_settings


def main(argv: Sequence[str] | None = None) -> int:
    """Run the load for `--seconds` (or until SIGINT or SIGTERM), then print the window summary as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=60)
    arguments = parser.parse_args(argv)
    settings = load_settings()
    if settings is None:
        return 2
    shutdown = ShutdownSignal()
    shutdown.install()
    with ThreadedLoad(settings.postgres, settings.load) as load:
        start = load.now()
        deadline = time.monotonic() + arguments.seconds
        while time.monotonic() < deadline and not shutdown.requested:
            time.sleep(1.0)
            window = load.summary(max(start, load.now() - 1.0), load.now())
            print(f"ops={window.ops:4d} errors={window.errors:3d} p99={window.p99_ms:8.1f} ms", flush=True)
        print(json.dumps(dataclasses.asdict(load.summary(start, load.now())), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`--seconds` (default 60). `with ThreadedLoad(...) as load:` runs the load; the `while time.monotonic() < deadline and not shutdown.requested:` loop sleeps one second at a time, then prints `ops`, `errors` and `p99` of the last second with `f"ops={window.ops:4d} errors={window.errors:3d} p99={window.p99_ms:8.1f} ms"` (`:4d` pads an integer to 4 columns, `:8.1f` a number to 8 columns with one decimal), with `flush=True` so each line appears at once. At the end the whole window is printed as indented JSON (`json.dumps(dataclasses.asdict(...), indent=2)`). Ctrl-C ends the loop early (the flag), and the `with` block stops the threads.

### The shutdown flag

`src/locks_lab/infrastructure/shutdown.py`, lines 1 to 29:

```python
"""Graceful shutdown: SIGINT and SIGTERM set a flag the work loops check between units of work."""

from __future__ import annotations

import signal
import threading
from types import FrameType


class ShutdownSignal:
    """A flag that SIGINT and SIGTERM set, which work loops check between units of work."""

    def __init__(self) -> None:
        self._requested = threading.Event()

    def install(self) -> None:
        """Route SIGINT and SIGTERM to `request`, so in-flight work finishes and connections close."""
        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, self._handle)

    def _handle(self, _number: int, _frame: FrameType | None) -> None:
        self.request()

    def request(self) -> None:
        self._requested.set()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()
```

`ShutdownSignal` wraps a `threading.Event`. `install` loops over `(signal.SIGINT, signal.SIGTERM)` and calls `signal.signal(number, self._handle)`, so both signals call `_handle(number, frame)` instead of killing the process (`frame` is the place in the code that was interrupted; it is ignored). `_handle` calls `request`, which sets the event. `requested` is a property that reads it. Nothing else happens in the handler, which is exactly the safe pattern. The replay and the load poll the flag between steps; the safe backfill also receives it (`should_stop`) and stops between batches.

### Shared start-up

`src/locks_lab/interfaces/common.py`, lines 19 to 27:

```python
def load_settings() -> Settings | None:
    """Read and validate the environment, configure logging, or print the problem and return None."""
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return None
    configure_logging(settings.log_level)
    return settings
```

Bad configuration is a normal outcome of a command line, not a crash: print one line on standard error, return `None`, and let `main` return `2`.

## Try it yourself

1. `make up db` then `make health; echo "exit=$?"` prints `ok postgres: 2,000,026 events` (or your row count) and `exit=0`.
2. `PGPASSWORD= .venv/bin/locks-lab-health; echo "exit=$?"` prints `configuration error: PGPASSWORD must be set and not empty (copy .env.example to .env)` and `exit=2`.
3. `make down` then `.venv/bin/locks-lab-health; echo "exit=$?"` (with your `.env` loaded) prints a `FAIL postgres: cannot query PostgreSQL: ...` line after a few retry warnings and `exit=1`.
4. `.venv/bin/python -m locks_lab.interfaces.run_cli --help` prints the usage with `--baseline-seconds` and `--output-dir`.
5. `.venv/bin/locks-lab-load --seconds abc; echo "exit=$?"` prints `usage: locks-lab-load [-h] [--seconds SECONDS]` and `locks-lab-load: error: argument --seconds: invalid int value: 'abc'`, with `exit=2` (argparse checks before the program does anything).
6. Start `make load SECONDS=60` and press Ctrl-C after a few seconds: it prints the summary JSON for the part that ran; `echo $?` right after a direct run of `.venv/bin/locks-lab-load` shows `0`. Start `.venv/bin/locks-lab-run` and press Ctrl-C: the log shows `interrupted; the table is left mid-lesson, the next run resets it first` and `echo $?` shows `130`.

## Mistakes people make

- Doing real work inside a signal handler.
- Returning exit code 0 after an error, so scripts and CI think it worked.
- Printing errors on standard output and mixing them with results.
- Calling `sys.exit()` deep inside a library function instead of returning to `main`.
- Forgetting that `docker stop` sends SIGTERM and kills with SIGKILL after 10 seconds if the program ignores it.

**How this repository avoids them.** The handler only sets a flag. Exit codes are documented and tested (`tests/unit/interfaces/test_cli.py`). Logs go to standard error and results to standard output. `main` returns codes; only the last two lines of each module turn the return value into an exit.

## Check yourself

1. What exit code means success? *0.*
2. What does 130 mean? *The process ended because of signal 2 (Ctrl-C): 128 + 2.*
3. What is a signal handler good for? *Setting a flag that the main loop checks, so the program can stop cleanly.*
4. Why do results go to standard output and logs to standard error? *So that redirecting or piping the results does not capture the logs.*
5. What does `raise SystemExit(main())` do? *Calls `main`, then ends the program with the number it returned as the exit code.*

## Further reading

- `argparse` tutorial (3.13): https://docs.python.org/3.13/howto/argparse.html
- `signal` module: https://docs.python.org/3.13/library/signal.html ; `threading.Event`: https://docs.python.org/3.13/library/threading.html#event-objects
- POSIX exit status and signals: https://pubs.opengroup.org/onlinepubs/9699919799/utilities/V3_chap02.html#tag_18_08_02

# Python type hints

## What it is

A **type hint** is a note in the code saying what kind of value a name, parameter or result should be: `def area(width: float, height: float) -> float:`. Python itself ignores hints when it runs the program. Separate tools, **type checkers** such as mypy, read them and report mismatches before the program runs. Hints also document the code for the next reader.

## Why this repository uses it

Every function in `src/` and `tests/` is typed and `mypy --strict` checks them in `make lint`. The typed *ports* in `application/ports.py` are also how the use cases name what they need from the database without importing it.

## Where it appears

| File | What it shows |
|---|---|
| `application/ports.py` | Seven `Protocol` classes: `LoadGenerator`, `LabTable`, `LockExperiments`, `SchemaChanges`, `PlanFlipLab`, `ArtifactStore`, `HealthProbe`. |
| `infrastructure/retry.py` | A generic function, `retry[T]`. |
| `infrastructure/postgres.py` | `psycopg.Connection[Any]`, `Iterator[...]` for a context manager. |
| `application/replay.py`, `report.py` | `Callable[[str], None]`, `TYPE_CHECKING`. |
| every module | `from __future__ import annotations` and hints on every definition. |

## How it works underneath

**Basic forms.** `x: int = 3` annotates a variable. `-> str` after a function's parameters annotates its result; `-> None` means it returns nothing.

**Containers.** `list[str]` is a list of text items. `dict[str, int]` maps text to whole numbers. `tuple[str, ...]` is a tuple of any length of text; `tuple[int, str]` is a tuple of exactly two items. `set[int]`.

**Unions.** `int | None` means "a whole number or None". Older code wrote `Optional[int]`.

**Abstract types** from `collections.abc` describe what a value can do rather than what it is: `Sequence[str]` (ordered, indexable, read-only use), `Mapping[str, int]` (dict-like, read-only use), `Iterable[int]` (can be looped over), `Iterator[int]` (produces values one at a time), `Callable[[str, int], bool]` (a function taking text and a number, returning a bool). Taking the abstract type as a parameter makes a function accept more kinds of arguments.

**`Any`** switches checking off for that value.

**Generics.** A function that works for any type but keeps the relationship between input and output uses a **type variable**: since Python 3.12, `def first[T](items: Sequence[T]) -> T:` declares `T` right after the name. If you pass `Sequence[str]` the result is `str`.

**Protocols (structural typing).** `class Reader(Protocol): def read(self) -> str: ...` describes a shape. *Any* class that has a matching `read` method counts as a `Reader`, without inheriting from it. This is how code can depend on an "interface" while the real classes stay independent.

**Forward references and `from __future__ import annotations`.** With this line at the top of a file, hints are not evaluated when the file loads; they stay as text. A class can then be named inside its own definition, and hints cost nothing at start-up.

**`TYPE_CHECKING`.** A constant that is `False` when the program runs and `True` for type checkers. Imports placed under `if TYPE_CHECKING:` exist only for hints, which avoids circular imports.

**`# type: ignore`** silences the checker on one line; it should be rare and explained.

**Libraries without hints** can hurt checking; most popular libraries ship hints (a `py.typed` marker) or have a separate package of stubs (`types-requests`).

## Walkthrough of this repository's use

### The ports

`src/locks_lab/application/ports.py`, lines 1 to 136:

```python
"""Ports: what the use cases need from the outside world. Adapters in `infrastructure` implement them."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from ..domain.locks import LockReport
from ..domain.outcomes import (
    ConflictOutcome,
    FlipOutcome,
    InterruptedBuild,
    QueueOutcome,
    RebuiltIndex,
    TableSize,
)
from ..domain.stats import WindowSummary


class LoadGenerator(Protocol):
    """The load script, already running: steady inserts, updates and reads, measured second by second."""

    def now(self) -> float:
        """The load's clock, to open and close a window."""
        ...

    def mark(self, label: str) -> None:
        """Label the per-second record, so a spike can be matched to the step that caused it."""
        ...

    def summary(self, start: float, end: float) -> WindowSummary:
        """What finished between two moments of `now()`."""
        ...

    def measure(self, seconds: float) -> WindowSummary:
        """Let the load run for `seconds` and summarize that stretch."""
        ...


class LabTable(Protocol):
    """The events table as a whole: back to the seed, and facts about it."""

    def reset(self) -> None:
        """Remove the lesson's column, indexes, constraint, statistics and every row beyond the seed."""
        ...

    def row_count(self) -> int:
        """Rows in the events table."""
        ...

    def size(self) -> TableSize:
        """Table size and dead row versions."""
        ...


class LockExperiments(Protocol):
    """The two experiments that need a second session holding a lock."""

    def lock_queue(self, hold_seconds: float) -> QueueOutcome:
        """A long read, then a naive ALTER behind it, with the lock views sampled mid-pile-up."""
        ...

    def forced_conflict(self, lock_timeout: str) -> ConflictOutcome:
        """A long read is open and the safe ALTER has a lock_timeout: it must fail fast."""
        ...


class SchemaChanges(Protocol):
    """The three changes, each the naive way and the safe way."""

    def add_flagged_column(self) -> int:
        """The expand step with lock_timeout and retry; returns the attempts it took."""
        ...

    def backfill_flagged(self, batch_size: int, pause_seconds: float, should_stop: Callable[[], bool]) -> int:
        """Fill the column for the existing rows in batches with a pause; returns the batches run."""
        ...

    def unflagged_rows(self) -> int:
        """Rows whose flagged column is still NULL."""
        ...

    def plain_index_build(self) -> float:
        """The naive CREATE INDEX (writes wait for it), dropped again; returns the build seconds."""
        ...

    def interrupted_concurrent_build(self) -> InterruptedBuild:
        """Start CREATE INDEX CONCURRENTLY and cancel it in its validation phase."""
        ...

    def rebuild_invalid_index(self) -> RebuiltIndex:
        """Drop the invalid index it left and build it again."""
        ...

    def naive_set_not_null(self) -> LockReport:
        """SET NOT NULL on a scratch column with no validated CHECK (a full scan under ACCESS EXCLUSIVE)."""
        ...

    def not_null_in_three_moves(self) -> dict[str, LockReport]:
        """NOT VALID check, VALIDATE, SET NOT NULL; each reported with the lock it held."""
        ...


class PlanFlipLab(Protocol):
    """The plan regression and its fix."""

    def run(self) -> FlipOutcome:
        """Load a correlated month, then plan the query before statistics catch up, after ANALYZE, after extended
        statistics."""
        ...


class ArtifactStore(Protocol):
    """Where the replay leaves its evidence."""

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        """Keep a plan next to its query."""
        ...

    def save_text(self, name: str, text: str) -> None:
        """Keep a text capture such as the lock queue."""
        ...

    def save_report(self, text: str) -> None:
        """Keep the results notes."""
        ...


class HealthProbe(Protocol):
    """A dependency's health check."""

    name: str

    def check(self) -> str:
        """Return a short description of what is healthy. Raise `ProbeFailedError` when it is not."""
        ...
```

- Line 3 `from __future__ import annotations` (explained above). Lines 5 and 6 import `Callable`, `Sequence` and `Protocol`; lines 8 to 17 import value types from the domain (`LockReport`, the outcomes, `WindowSummary`), which is allowed: application may import domain.
- `class LoadGenerator(Protocol):` is a **protocol class** (a described shape): the load script as the use cases see it. `now() -> float`, `mark(label: str) -> None`, `summary(start: float, end: float) -> WindowSummary`, `measure(seconds: float) -> WindowSummary`. The `...` (Ellipsis) as a body means "no implementation here"; the real class is `ThreadedLoad` in `infrastructure/load_runner.py`, which does *not* inherit from `LoadGenerator`; it matches it by having methods of the same names and types, which mypy verifies wherever a `ThreadedLoad` is passed to `ReplayLesson`. The test fake matches it too.
- `LabTable` (`reset`, `row_count`, `size() -> TableSize`), `LockExperiments` (`lock_queue(hold_seconds: float) -> QueueOutcome`, `forced_conflict(lock_timeout: str) -> ConflictOutcome`), `PlanFlipLab` (`run() -> FlipOutcome`) are small ports, each implemented by one infrastructure class.
- `SchemaChanges` has eight methods. Look at `def backfill_flagged(self, batch_size: int, pause_seconds: float, should_stop: Callable[[], bool]) -> int:` — `Callable[[], bool]` is "a function taking nothing and returning a bool", so the adapter can ask "should I stop?" between batches without knowing about signals. And `def not_null_in_three_moves(self) -> dict[str, LockReport]:` returns a dictionary from move name to report.
- `ArtifactStore` (`save_plan`, `save_text`, `save_report`) and `class HealthProbe(Protocol): name: str` (an *attribute* as part of the shape, plus `check`).

### A generic function

`src/locks_lab/infrastructure/retry.py`, lines 10 to 20:

```python
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
```

`def retry[T](...)` declares a type variable `T`. `operation: Callable[[], T]` is a function taking no arguments and returning a `T`; the result of `retry` is also a `T`. So `retry(open_connection, ...)` has the type that `open_connection` returns. `retry_on: tuple[type[BaseException], ...]` is a tuple of error *classes* (`type[...]` means "the class itself, not an instance"). `sleep: Callable[[float], None] = time.sleep` has a default of the real `time.sleep`, which tests replace. `rng: random.Random | None = None` is "a random generator or nothing". `on_retry: Callable[[int, BaseException], None] | None` is an optional function receiving the attempt number and the error. The bare `*` makes everything after `operation` keyword-only.

### Hints for a context manager

`src/locks_lab/infrastructure/postgres.py`, lines 60 to 67:

```python
@contextmanager
def session(
    settings: PostgresSettings, *, autocommit: bool = True, application_name: str = "locks-lab"
) -> Iterator[psycopg.Connection[Any]]:
    """A connection that is always closed, also when the block raises."""
    connection = connect(settings, autocommit=autocommit, application_name=application_name)
    try:
        yield connection
```

A function decorated with `@contextmanager` that `yield`s once is annotated as returning `Iterator[psycopg.Connection[Any]]`: the type of what it yields. `psycopg.Connection[Any]` is a generic class; `Any` says "I do not constrain what rows look like".

### Callable defaults and TYPE_CHECKING

`src/locks_lab/application/replay.py`, lines 65 to 79:

```python
    def __init__(
        self,
        *,
        load: LoadGenerator,
        table: LabTable,
        scenarios: Scenarios,
        store: ArtifactStore,
        baseline_seconds: int,
        closing_seconds: int = 20,
        batch_size: int,
        pause_seconds: float,
        host_load: HostLoad | None = None,
        progress: Callable[[str], None] = lambda _message: None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
```
`src/locks_lab/application/report.py`, lines 1 to 12:

```python
"""The results notes: a pure function from what was measured to Markdown."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain.lesson import FLIP_PLAN_LABELS
from ..domain.stats import Bar, WindowSummary

if TYPE_CHECKING:
    from .replay import LessonResult

```

`progress: Callable[[str], None] = lambda _message: None` is a function taking text and returning nothing, with a do-nothing default. `should_stop: Callable[[], bool] = lambda: False` is a function taking nothing and returning a bool; the default never stops. In `scenarios.py`, `pause: Callable[[float], None]` is a function that takes seconds and returns nothing (`time.sleep` fits; so does a test's recorder). In `report.py` the import of `LessonResult` happens only under `if TYPE_CHECKING:`, because `replay.py` imports `report.py` and importing back at run time would loop. With `from __future__ import annotations`, the hint `result: LessonResult` is never evaluated, so the name needs not exist at run time.

### Optional values

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

`-> Settings | None` makes callers handle the failure case; mypy rejects code that uses the result without checking `None` first (`if settings is None: return 2` in the commands).

## Try it yourself

1. `.venv/bin/mypy` — checks all of `src` and `tests`; prints `Success: no issues found in 60 source files`.
2. Make a deliberate mistake: in `src/locks_lab/domain/host.py` change `def loaded(self) -> bool:` to `-> str` and run `.venv/bin/mypy`. It reports `src/locks_lab/domain/host.py:18: error: Incompatible return value type (got "bool", expected "str")  [return-value]` and `Found 1 error in 1 file`. Undo with `git checkout src/locks_lab/domain/host.py`.
3. `.venv/bin/python -c "from locks_lab.application.ports import LoadGenerator; print(LoadGenerator.__mro__)"` shows that `LoadGenerator` is a `Protocol` class.
4. `.venv/bin/python -c "import typing, locks_lab.infrastructure.retry as r; print(r.retry.__type_params__)"` prints `(T,)`, the type parameter.

## Mistakes people make

- Thinking hints are enforced at run time.
- Using `Any` to make an error go away.
- Annotating a parameter with a concrete `list` when a `Sequence` would do.
- Returning `None` in some branches of a function annotated with a non-optional result.
- Using a mutable `list` default under the hint `list[int]`.

**How this repository avoids them.** `mypy --strict` refuses untyped definitions and unexplained `Any`. The ports are small. The one generic function is covered by tests. `# type: ignore` is not used in `src/`.

## Check yourself

1. Does Python stop a program that passes text where `int` was hinted? *No; only a type checker reports it.*
2. What does `tuple[str, ...]` mean? *A tuple of any length whose items are text.*
3. What is a Protocol? *A description of required methods; any class with those methods matches it without inheriting.*
4. Why would you put an import under `if TYPE_CHECKING:`? *The import is only needed for hints, and skipping it at run time avoids circular imports and start-up cost.*
5. What does `def f[T](x: T) -> T` declare? *A function generic in `T`: whatever type goes in, the same type comes out.*

## Further reading

- Typing documentation (Python 3.13 `typing` module): https://docs.python.org/3.13/library/typing.html
- The typing specification and tutorial: https://typing.python.org/en/latest/
- PEP 695 (type parameter syntax, Python 3.12): https://peps.python.org/pep-0695/

# Python dataclasses

## What it is

A **dataclass** is a Python class whose main job is to hold a few named values. You list the fields with their types, add the decorator `@dataclass`, and Python writes the boring methods for you: the one that sets the fields when you create an object (`__init__`), the one that prints it (`__repr__`), and the one that compares two objects (`__eq__`). The decorator lives in the standard library module `dataclasses`.

## Why this repository uses it

The code passes small bundles of facts between layers: one finished statement of the load, a second of the load, a summary of a window, a lock request, an experiment's outcome, the settings. Dataclasses make each one a named, read-only, self-describing value with almost no code. The measurements of the lab are exactly such values.

## Where it appears

| File | Dataclasses |
|---|---|
| `domain/stats.py` | `Sample`, `Tick`, `WindowSummary`, `Bar` |
| `domain/locks.py` | `WaitingSession`, `LockRequest`, `LockSnapshot`, `LockReport` |
| `domain/outcomes.py` | `TableSize`, `ConflictOutcome`, `QueueOutcome`, `InterruptedBuild`, `RebuiltIndex`, `FlipOutcome` |
| `domain/flip.py` | `FlipPlan` |
| `domain/host.py` | `HostLoad` |
| `application/scenarios.py` | `LockQueueResult`, `SafeMigrationResult`, `PlainIndexResult`, `ConcurrentIndexResult`, `NaiveNotNullResult`, `SafeNotNullResult`, `FlipResult` |
| `application/replay.py` | `LessonResult` |
| `application/health.py` | `ProbeResult`, `HealthReport` |
| `infrastructure/settings.py` | `PostgresSettings`, `LoadSettings`, `MigrationSettings`, `Settings` |

## How it works underneath

```python
@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float
```

- `x: float` is a **field declaration**: a name, a colon and a type hint. It is not an assignment.
- **Creating an object.** `Point(1.0, 2.0)` or `Point(x=1.0, y=2.0)`. The generated `__init__` assigns the values to `self.x` and `self.y`.
- **`repr`.** `print(Point(1.0, 2.0))` shows `Point(x=1.0, y=2.0)`.
- **`eq`.** Two objects with equal fields are equal (`==`).
- **`frozen=True`.** The object is read-only after creation; `p.x = 3` raises `FrozenInstanceError`. A frozen dataclass is also **hashable**, so it can be a dictionary key or set member. Immutable values are easier to reason about, and safe to share between threads.
- **`slots=True`.** Python normally stores an object's attributes in a hidden dictionary. With slots it reserves fixed places instead: less memory, and a typo like `p.z = 1` is an error instead of silently adding an attribute.
- **Defaults.** `limit: int = 5` makes a field optional. Fields with defaults must come after fields without. A mutable default such as a list must use `field(default_factory=list)`.
- **`field(repr=False)`** hides one field from the printed form: used for secrets, so a password is never printed by accident.
- **Methods and properties** can be added like in any class.
- **Order.** The order of the fields is the order of the positional arguments.

A dataclass is not checked at run time: `Point("a", "b")` is accepted. The type hints are for tools like mypy and for readers.

## Walkthrough of this repository's use

All thirty use the same decorator, `@dataclass(frozen=True, slots=True)`: read-only and memory-lean. Frozen matters here for a concrete reason: the load script's threads and the main thread share these values, and a value that cannot change cannot be changed by accident from two places.

`src/locks_lab/domain/stats.py`, lines 24 to 45:

```python
@dataclass(frozen=True, slots=True)
class Sample:
    """One finished statement of the load."""

    finished_at: float
    operation: str
    milliseconds: float
    ok: bool


@dataclass(frozen=True, slots=True)
class Tick:
    """One second of the load as the reporter saw it."""

    t: float
    ops: int
    errors: int
    p99_ms: float
    oldest_inflight_ms: float


def make_tick(now: float, window_start: float, samples: Sequence[Sample], inflight_ages_ms: Sequence[float]) -> Tick:
```

`Sample` is one finished statement (`finished_at`, `operation`, `milliseconds`, `ok`). The load creates tens of thousands of them, which is where `slots=True` (no per-object dictionary) helps. `Tick` is one second as the reporter saw it: `t`, `ops`, `errors`, `p99_ms`, `oldest_inflight_ms`.

`src/locks_lab/domain/stats.py`, lines 58 to 114:

```python
@dataclass(frozen=True, slots=True)
class WindowSummary:
    """A stretch of the load: rate, errors, latency and stalls."""

    seconds: float
    ops: int
    ops_per_second: float
    errors: int
    p50_ms: float
    p99_ms: float
    max_ms: float
    worst_second_p99_ms: float
    stalled_seconds: int


def summarize(samples: Sequence[Sample], ticks: Sequence[Tick], start: float, end: float) -> WindowSummary:
    """Summarize what finished in [start, end); a tick counts when its midpoint lies inside the window."""
    window = [sample for sample in samples if start <= sample.finished_at < end]
    inside = [tick for tick in ticks if start <= tick.t - 0.5 < end]
    latencies = [sample.milliseconds for sample in window]
    seconds = max(end - start, 1e-9)
    return WindowSummary(
        seconds=round(seconds, 1),
        ops=len(window),
        ops_per_second=round(len(window) / seconds, 1),
        errors=sum(not sample.ok for sample in window),
        p50_ms=round(percentile(latencies, 0.50), 2),
        p99_ms=round(percentile(latencies, 0.99), 2),
        max_ms=round(max(latencies, default=0.0), 1),
        worst_second_p99_ms=max((tick.p99_ms for tick in inside), default=0.0),
        stalled_seconds=sum(tick.oldest_inflight_ms >= STALL_MS for tick in inside),
    )


@dataclass(frozen=True, slots=True)
class Bar:
    """The lesson's bar for a change that must not hurt.

    p99 at most `factor` times the baseline, no errors, no stalled second.
    """

    baseline_p99_ms: float
    factor: float = 2.0

    @classmethod
    def bracketing(cls, opening: WindowSummary, closing: WindowSummary, factor: float = 2.0) -> Bar:
        """The bar from the higher of two baselines taken before and after, because other work on the machine moves
        p99 as much as a migration does."""
        return cls(max(opening.p99_ms, closing.p99_ms), factor)

    @property
    def limit_ms(self) -> float:
        return self.baseline_p99_ms * self.factor

    def allows(self, window: WindowSummary) -> bool:
        """True when the window stayed within the bar."""
        return window.p99_ms <= self.limit_ms and window.errors == 0 and window.stalled_seconds == 0
```

`WindowSummary` has nine fields. `Bar` has `baseline_p99_ms: float` and `factor: float = 2.0` (a default, so it comes last), a property `limit_ms`, a method `allows` and a class method `bracketing` that builds a `Bar` from two summaries.

`src/locks_lab/domain/locks.py`, lines 63 to 69:

```python
@dataclass(frozen=True, slots=True)
class LockReport:
    """A statement run in its own transaction: how long it took, the lock modes it held, and the tries it needed."""

    seconds: float
    lock_modes: tuple[str, ...]
    attempts: int = 1
```

`LockReport` has `attempts: int = 1`: a field with a default is optional when the object is created (`LockReport(seconds, modes)` or `LockReport(seconds, modes, tries)`).

`src/locks_lab/domain/outcomes.py`, lines 34 to 56:

```python
@dataclass(frozen=True, slots=True)
class InterruptedBuild:
    """A CREATE INDEX CONCURRENTLY cancelled on purpose: what it left behind."""

    cancelled: bool
    invalid_indexes: tuple[str, ...]
    ready_but_invalid: bool


@dataclass(frozen=True, slots=True)
class RebuiltIndex:
    """The invalid index dropped and the build run again."""

    seconds: float
    valid: bool


@dataclass(frozen=True, slots=True)
class FlipOutcome:
    """The correlated month: how many rows match, and the three captured plans' lines by name."""

    actual_rows: int
    plans: dict[str, tuple[str, ...]]
```

`InterruptedBuild` and `FlipOutcome` show fields that hold tuples and a dictionary of tuples. A frozen dataclass can contain such containers, but the *container itself* (a dict or list) can still be changed from outside; the dataclass only freezes which object each field refers to. The code treats them as read-only by convention and type hints (`tuple`, not `list`).

`src/locks_lab/infrastructure/settings.py`, lines 51 to 93:

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
```

`PostgresSettings` has `password: str = field(repr=False)`: a required field hidden from the printed form, so `print(settings.postgres)` never shows the password. `LoadSettings` and `MigrationSettings` group the load's and the migration's knobs; `Settings` holds them all plus the baseline lengths, the SQL folder and the log level, with a `@classmethod` (`from_env`) that builds an instance from environment variables (the environment note).

`src/locks_lab/domain/host.py`, lines 8 to 18:

```python
@dataclass(frozen=True, slots=True)
class HostLoad:
    """The 1-minute load average and the CPU count at the start of a measurement."""

    load_average: float
    cpus: int

    @property
    def loaded(self) -> bool:
        """True when more than half a runnable task per CPU was waiting: timings are inflated."""
        return self.load_average > self.cpus / 2
```

`HostLoad` shows a dataclass with a property. `loaded` is not a field; it is computed from two fields every time it is read.

## Try it yourself

1. `.venv/bin/python -c "from locks_lab.infrastructure.settings import PostgresSettings as P; print(P('h',1,'d','u','SECRET',5,1,0))"` prints the object without the word `SECRET`: `PostgresSettings(host='h', port=1, database='d', user='u', connect_timeout_seconds=5, statement_timeout_ms=1, max_parallel_workers_per_gather=0)`.
2. `.venv/bin/python -c "from locks_lab.domain.host import HostLoad as H; h=H(1.0,4); h.cpus=8"` ends with `dataclasses.FrozenInstanceError: cannot assign to field 'cpus'`.
3. `.venv/bin/python -c "from locks_lab.domain.host import HostLoad as H; print(H(1.0,4)==H(1.0,4), hash(H(1.0,4))==hash(H(1.0,4)))"` prints `True True`.
4. `.venv/bin/python -c "from locks_lab.domain.host import HostLoad as H; h=H(1.0,4); h.extra=1"` is refused with a `TypeError` whose text starts `super(type, obj): obj (instance of HostLoad) is not an instance or subtype of type (HostLoad)`. That odd message is how Python 3.13 reports an unknown attribute on an object that is both frozen and slotted; the point is that the new attribute is not accepted.

## Mistakes people make

- Mutable defaults (`items: list = []`): Python refuses; use `field(default_factory=list)`.
- Putting a field with a default before one without.
- Assuming type hints validate input.
- Making an object frozen and then trying to change it: create a new one with `dataclasses.replace(obj, field=new_value)`.
- Printing an object that holds a password.

**How this repository avoids them.** All dataclasses are frozen. No field has a mutable default. The password field is hidden from `repr`. mypy checks the types that the dataclasses declare.

## Check yourself

1. What does `@dataclass` write for you? *`__init__`, `__repr__` and `__eq__` (and more, depending on the options).*
2. What does `frozen=True` prevent? *Changing a field after the object is created.*
3. What does `slots=True` do? *It stores attributes in fixed slots: less memory and no accidental new attributes.*
4. What is `field(repr=False)` for? *Hiding a field from the printed form of the object, for example a password.*
5. Do dataclasses check types when you create an object? *No; the type hints are only for tools and readers.*

## Further reading

- `dataclasses` module (Python 3.13): https://docs.python.org/3.13/library/dataclasses.html

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

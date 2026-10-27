"""Use cases: each experiment of the lesson, measured against the running load.

Every method takes the load as a parameter where it needs to look at it, and returns a plain result. The replay
chains them with long windows; the tests call them with short ones.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..domain.flip import FlipPlan, parse_flip_plan
from ..domain.locks import LockReport, LockSnapshot
from ..domain.outcomes import ConflictOutcome, InterruptedBuild, TableSize
from ..domain.stats import WindowSummary
from .ports import LabTable, LoadGenerator, LockExperiments, PlanFlipLab, SchemaChanges

SETTLE_SECONDS = 2.0  # let operations that were blocked finish before a window is summarized


@dataclass(frozen=True, slots=True)
class LockQueueResult:
    """The pile-up behind a naive ALTER."""

    snapshot: LockSnapshot
    during: WindowSummary
    after: WindowSummary
    alter_seconds: float
    hold_seconds: float


@dataclass(frozen=True, slots=True)
class SafeMigrationResult:
    """The column added with a lock_timeout and backfilled in batches."""

    summary: WindowSummary
    seconds: float
    batches: int
    add_column_attempts: int
    rows_still_null: int


@dataclass(frozen=True, slots=True)
class PlainIndexResult:
    """The naive index build and what the load felt."""

    build_seconds: float
    summary: WindowSummary


@dataclass(frozen=True, slots=True)
class ConcurrentIndexResult:
    """The interrupted concurrent build, its cleanup and the rebuild under load."""

    interrupted: InterruptedBuild
    build_seconds: float
    summary: WindowSummary
    valid_after_rebuild: bool


@dataclass(frozen=True, slots=True)
class NaiveNotNullResult:
    """SET NOT NULL with no validated CHECK."""

    report: LockReport
    summary: WindowSummary


@dataclass(frozen=True, slots=True)
class SafeNotNullResult:
    """NOT NULL in three moves."""

    steps: dict[str, LockReport]
    summary: WindowSummary


@dataclass(frozen=True, slots=True)
class FlipResult:
    """The plan regression: the row count and the three plans, parsed."""

    actual_rows: int
    plans: dict[str, FlipPlan]
    lines: dict[str, tuple[str, ...]]


class Scenarios:
    """The lesson's experiments over the ports."""

    def __init__(
        self,
        *,
        table: LabTable,
        locks: LockExperiments,
        changes: SchemaChanges,
        flip: PlanFlipLab,
        pause: Callable[[float], None],
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self._table = table
        self._locks = locks
        self._changes = changes
        self._flip = flip
        self._pause = pause
        self._should_stop = should_stop

    def lock_queue(self, load: LoadGenerator, hold_seconds: float = 6.0) -> LockQueueResult:
        """Step 2: a long read, then a naive ALTER behind it."""
        start = load.now()
        outcome = self._locks.lock_queue(hold_seconds)
        during = load.summary(start, load.now())
        after = load.measure(3)
        return LockQueueResult(outcome.snapshot, during, after, outcome.alter_seconds, hold_seconds)

    def forced_conflict(self, lock_timeout: str = "1s") -> ConflictOutcome:
        """Step 3: the safe ALTER must give up at its lock_timeout, then the queue it joined drains."""
        outcome = self._locks.forced_conflict(lock_timeout)
        self._pause(SETTLE_SECONDS)  # operations queued behind the failed ALTER finish first
        return outcome

    def safe_migration(self, load: LoadGenerator, batch_size: int, pause_seconds: float) -> SafeMigrationResult:
        """Step 3: add the column with a lock_timeout, backfill in batches, and summarize the load meanwhile."""
        start = load.now()
        attempts = self._changes.add_flagged_column()
        batches = self._changes.backfill_flagged(batch_size, pause_seconds, self._should_stop)
        end = load.now()
        return SafeMigrationResult(
            summary=load.summary(start, end),
            seconds=end - start,
            batches=batches,
            add_column_attempts=attempts,
            rows_still_null=self._changes.unflagged_rows(),
        )

    def plain_index(self, load: LoadGenerator) -> PlainIndexResult:
        """Step 4, the naive way: writes wait for the whole build."""
        start = load.now()
        build_seconds = self._changes.plain_index_build()
        self._pause(SETTLE_SECONDS)
        return PlainIndexResult(build_seconds, load.summary(start, load.now()))

    def concurrent_index(self, load: LoadGenerator) -> ConcurrentIndexResult:
        """Step 4: interrupt a concurrent build on purpose, find the invalid index, drop it, rebuild under load."""
        interrupted = self._changes.interrupted_concurrent_build()
        start = load.now()
        rebuilt = self._changes.rebuild_invalid_index()
        self._pause(SETTLE_SECONDS)
        return ConcurrentIndexResult(interrupted, rebuilt.seconds, load.summary(start, load.now()), rebuilt.valid)

    def naive_not_null(self, load: LoadGenerator) -> NaiveNotNullResult:
        """Step 5, the naive way: a scan under ACCESS EXCLUSIVE."""
        start = load.now()
        report = self._changes.naive_set_not_null()
        self._pause(SETTLE_SECONDS)
        return NaiveNotNullResult(report, load.summary(start, load.now()))

    def safe_not_null(self, load: LoadGenerator) -> SafeNotNullResult:
        """Step 5: NOT VALID, VALIDATE, SET NOT NULL."""
        start = load.now()
        steps = self._changes.not_null_in_three_moves()
        self._pause(SETTLE_SECONDS)
        return SafeNotNullResult(steps, load.summary(start, load.now()))

    def plan_flip(self) -> FlipResult:
        """Step 6: stale statistics, then ANALYZE, then extended statistics."""
        outcome = self._flip.run()
        return FlipResult(
            outcome.actual_rows,
            {name: parse_flip_plan(lines) for name, lines in outcome.plans.items()},
            outcome.plans,
        )

    def table_size(self) -> TableSize:
        return self._table.size()

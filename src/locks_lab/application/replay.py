"""Use case: replay the lesson with the load running throughout.

Baseline, the lock pile-up, the safe migration, the concurrent index, NOT NULL in three moves, the plan flip, and a
closing baseline that brackets the changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..domain.errors import LessonInterruptedError
from ..domain.host import HostLoad
from ..domain.outcomes import ConflictOutcome, TableSize
from ..domain.stats import Bar, WindowSummary
from .ports import ArtifactStore, LabTable, LoadGenerator
from .report import render_results
from .scenarios import (
    ConcurrentIndexResult,
    FlipResult,
    LockQueueResult,
    NaiveNotNullResult,
    PlainIndexResult,
    SafeMigrationResult,
    SafeNotNullResult,
    Scenarios,
)


@dataclass(frozen=True, slots=True)
class LessonResult:
    """Everything the replay measured."""

    rows: int
    baseline_seconds: int
    opening: WindowSummary
    closing: WindowSummary
    size_before: TableSize
    size_after_backfill: TableSize
    lock_queue: LockQueueResult
    conflict: ConflictOutcome
    safe: SafeMigrationResult
    plain_index: PlainIndexResult
    concurrent_index: ConcurrentIndexResult
    naive_not_null: NaiveNotNullResult
    safe_not_null: SafeNotNullResult
    flip: FlipResult
    batch_size: int
    pause_seconds: float
    host_load: HostLoad | None = None

    @property
    def bar(self) -> Bar:
        """Twice the higher of the opening and closing baselines."""
        return Bar.bracketing(self.opening, self.closing)


class ReplayLesson:
    """Runs the scenarios in the lesson's order against the running load and keeps the evidence.

    `should_stop` is polled between steps; when it returns true the replay raises `LessonInterruptedError` and leaves
    the table to be reset by the next run.
    """

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
        self._load = load
        self._table = table
        self._scenarios = scenarios
        self._store = store
        self._baseline_seconds = baseline_seconds
        self._closing_seconds = closing_seconds
        self._batch_size = batch_size
        self._pause_seconds = pause_seconds
        self._host_load = host_load
        self._progress = progress
        self._should_stop = should_stop

    def run(self) -> LessonResult:
        """Replay every step, write the notes, and return what was measured."""
        self._step("reset to the seed's rows")
        self._table.reset()
        rows = self._table.row_count()

        self._step(f"step 1: baseline, {self._baseline_seconds} s of steady load")
        opening = self._load.measure(self._baseline_seconds)
        size_before = self._table.size()

        self._step("step 2: a long read, then a naive ALTER behind it")
        queue = self._scenarios.lock_queue(self._load)
        self._store.save_text("lock_queue.txt", queue.snapshot.format())
        self._table.reset()

        self._step("step 3: the safe migration")
        conflict = self._scenarios.forced_conflict()
        self._table.reset()
        safe = self._scenarios.safe_migration(self._load, self._batch_size, self._pause_seconds)
        size_after = self._table.size()

        self._step("step 4: the index")
        plain = self._scenarios.plain_index(self._load)
        concurrent = self._scenarios.concurrent_index(self._load)

        self._step("step 5: NOT NULL")
        naive = self._scenarios.naive_not_null(self._load)
        three_moves = self._scenarios.safe_not_null(self._load)

        self._step("step 6: the plan flip")
        flip = self._scenarios.plan_flip()
        for name, lines in flip.lines.items():
            self._store.save_plan(name, lines)
        self._table.reset()

        self._step("closing baseline: the machine's own noise, to bracket the changes")
        closing = self._load.measure(self._closing_seconds)

        result = LessonResult(
            rows=rows,
            baseline_seconds=self._baseline_seconds,
            opening=opening,
            closing=closing,
            size_before=size_before,
            size_after_backfill=size_after,
            lock_queue=queue,
            conflict=conflict,
            safe=safe,
            plain_index=plain,
            concurrent_index=concurrent,
            naive_not_null=naive,
            safe_not_null=three_moves,
            flip=flip,
            batch_size=self._batch_size,
            pause_seconds=self._pause_seconds,
            host_load=self._host_load,
        )
        self._store.save_report(render_results(result))
        return result

    def _step(self, label: str) -> None:
        if self._should_stop():
            raise LessonInterruptedError("stopped between steps")
        self._progress(label)
        self._load.mark(label)

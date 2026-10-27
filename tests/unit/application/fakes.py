"""In-memory stand-ins for the ports, so the scenarios can be tested without a database or threads."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from locks_lab.domain.locks import LockReport, LockRequest, LockSnapshot, WaitingSession
from locks_lab.domain.outcomes import (
    ConflictOutcome,
    FlipOutcome,
    InterruptedBuild,
    QueueOutcome,
    RebuiltIndex,
    TableSize,
)
from locks_lab.domain.stats import WindowSummary


def window(
    p99: float = 5.0, *, errors: int = 0, stalled: int = 0, ops: int = 100, max_ms: float = 20.0
) -> WindowSummary:
    return WindowSummary(10.0, ops, ops / 10, errors, 1.0, p99, max_ms, p99, stalled)


class FakeLoad:
    """A load whose windows are scripted; records the marks and how long it was asked to run."""

    def __init__(self, windows: Sequence[WindowSummary] | None = None) -> None:
        self.marks: list[str] = []
        self.measured: list[float] = []
        self._clock = 0.0
        self._windows = list(windows or [])

    def now(self) -> float:
        self._clock += 1.0
        return self._clock

    def mark(self, label: str) -> None:
        self.marks.append(label)

    def summary(self, start: float, end: float) -> WindowSummary:
        return self._windows.pop(0) if self._windows else window()

    def measure(self, seconds: float) -> WindowSummary:
        self.measured.append(seconds)
        return self.summary(0.0, seconds)


class FakeTable:
    """Counts resets; the first size read is the clean table, later ones the table after the backfill."""

    def __init__(self) -> None:
        self.resets = 0
        self._size_reads = 0

    def reset(self) -> None:
        self.resets += 1

    def row_count(self) -> int:
        return 2_000_000

    def size(self) -> TableSize:
        self._size_reads += 1
        return TableSize("194 MB", 0) if self._size_reads == 1 else TableSize("357 MB", 1_368_325)


SNAPSHOT = LockSnapshot(
    waiting=(WaitingSession(391, "naive-alter", (390,), 3.0, "ALTER TABLE events ADD COLUMN flagged boolean"),),
    queue=(
        LockRequest(390, "long-transaction", "AccessShareLock", True),
        LockRequest(391, "naive-alter", "AccessExclusiveLock", False),
    ),
)


class FakeLocks:
    def __init__(self) -> None:
        self.holds: list[float] = []
        self.timeouts: list[str] = []

    def lock_queue(self, hold_seconds: float) -> QueueOutcome:
        self.holds.append(hold_seconds)
        return QueueOutcome(SNAPSHOT, hold_seconds)

    def forced_conflict(self, lock_timeout: str) -> ConflictOutcome:
        self.timeouts.append(lock_timeout)
        return ConflictOutcome(True, 1.0)


class FakeChanges:
    """Records the order of the changes; the backfill honors the stop callback between batches."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def add_flagged_column(self) -> int:
        self.calls.append("add_flagged_column")
        return 1

    def backfill_flagged(self, batch_size: int, pause_seconds: float, should_stop: Callable[[], bool]) -> int:
        self.calls.append(f"backfill {batch_size} {pause_seconds}")
        return 0 if should_stop() else 100

    def unflagged_rows(self) -> int:
        return 0

    def plain_index_build(self) -> float:
        self.calls.append("plain_index_build")
        return 0.8

    def interrupted_concurrent_build(self) -> InterruptedBuild:
        self.calls.append("interrupted_concurrent_build")
        return InterruptedBuild(True, ("idx_events_device_created",), True)

    def rebuild_invalid_index(self) -> RebuiltIndex:
        self.calls.append("rebuild_invalid_index")
        return RebuiltIndex(0.9, True)

    def naive_set_not_null(self) -> LockReport:
        self.calls.append("naive_set_not_null")
        return LockReport(0.18, ("AccessExclusiveLock",))

    def not_null_in_three_moves(self) -> dict[str, LockReport]:
        self.calls.append("not_null_in_three_moves")
        return {
            "add_check_not_valid": LockReport(0.0005, ("AccessExclusiveLock",)),
            "validate": LockReport(0.14, ("ShareUpdateExclusiveLock",)),
            "set_not_null": LockReport(0.0007, ("AccessExclusiveLock",)),
        }


STALE = (
    "Sort  (cost=1..2 rows=1 width=1)",
    "  ->  Seq Scan on events  (cost=0..1 rows=1 width=1)",
    "Execution Time: 175.0 ms",
)
INDEXED = (
    "Index Scan Backward using idx_events_created_at on events  (cost=0..1 rows=150000 width=1)",
    "Execution Time: 0.07 ms",
)


class FakeFlip:
    def run(self) -> FlipOutcome:
        return FlipOutcome(
            150_000,
            {"f1_stale_statistics": STALE, "f2_after_analyze": INDEXED, "f3_after_extended_statistics": INDEXED},
        )


class RecordingStore:
    def __init__(self) -> None:
        self.plans: dict[str, tuple[str, ...]] = {}
        self.texts: dict[str, str] = {}
        self.report: str | None = None

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        self.plans[name] = tuple(lines)

    def save_text(self, name: str, text: str) -> None:
        self.texts[name] = text

    def save_report(self, text: str) -> None:
        self.report = text

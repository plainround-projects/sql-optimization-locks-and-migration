"""What the experiments hand back, as plain values."""

from __future__ import annotations

from dataclasses import dataclass

from .locks import LockSnapshot


@dataclass(frozen=True, slots=True)
class TableSize:
    """The events table's size and the dead row versions an update-heavy change leaves behind."""

    pretty: str
    dead_rows: int


@dataclass(frozen=True, slots=True)
class ConflictOutcome:
    """The safe ALTER met a long read: did it give up at lock_timeout, and how long did it wait?"""

    failed_fast: bool
    seconds: float


@dataclass(frozen=True, slots=True)
class QueueOutcome:
    """The naive ALTER behind a long read: the lock views mid-pile-up, and how long the ALTER waited."""

    snapshot: LockSnapshot
    alter_seconds: float


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

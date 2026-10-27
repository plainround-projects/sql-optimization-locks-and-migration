"""What the load script measures and how a window of it is summarized.

A second's p99 counts the operations that finished in it and the age of any operation still waiting, so a stall
shows up as a high p99 even when nothing completes (otherwise a full outage would look like silence).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

STALL_MS = 500  # an operation older than this at a one-second tick makes that second a stalled one


def percentile(values: Sequence[float], fraction: float) -> float:
    """The nearest-rank percentile (`fraction` in 0..1); 0.0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


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
    """The tick for the window [window_start, now): finished samples plus the ages of operations still waiting."""
    finished = [sample for sample in samples if window_start <= sample.finished_at < now]
    latencies = [sample.milliseconds for sample in finished] + list(inflight_ages_ms)
    return Tick(
        t=now,
        ops=len(finished),
        errors=sum(not sample.ok for sample in finished),
        p99_ms=percentile(latencies, 0.99),
        oldest_inflight_ms=max(inflight_ages_ms, default=0.0),
    )


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

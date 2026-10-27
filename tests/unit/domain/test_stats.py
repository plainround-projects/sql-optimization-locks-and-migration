import pytest

from locks_lab.domain.stats import STALL_MS, Bar, Sample, Tick, make_tick, percentile, summarize


def sample(at: float, ms: float, ok: bool = True) -> Sample:
    return Sample(at, "insert", ms, ok)


def test_percentile_is_nearest_rank():
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.5) == 3.0
    assert percentile(list(map(float, range(1, 101))), 0.99) == 99.0


def test_percentile_of_nothing_is_zero_and_of_one_value_is_that_value():
    assert percentile([], 0.99) == 0.0
    assert percentile([7.0], 0.99) == 7.0


def test_a_tick_counts_finished_statements_and_the_age_of_those_still_waiting():
    samples = [sample(10.2, 2.0), sample(10.7, 4.0, ok=False), sample(9.0, 99.0)]
    tick = make_tick(11.0, 10.0, samples, [3000.0])
    assert (tick.ops, tick.errors) == (2, 1)
    assert tick.p99_ms == 3000.0, "a stalled operation shows even though it has not finished"
    assert tick.oldest_inflight_ms == 3000.0


def test_a_quiet_second_has_a_zero_tick():
    assert make_tick(11.0, 10.0, [], []) == Tick(11.0, 0, 0, 0.0, 0.0)


def test_a_window_summary_covers_what_finished_inside_it():
    samples = [sample(1.0, 2.0), sample(1.5, 4.0), sample(2.5, 6.0, ok=False), sample(9.0, 500.0)]
    ticks = [Tick(2.0, 2, 0, 4.0, 0.0), Tick(3.0, 1, 1, 6.0, 0.0), Tick(10.0, 0, 0, 999.0, 0.0)]
    summary = summarize(samples, ticks, 0.0, 4.0)
    assert (summary.ops, summary.errors, summary.max_ms) == (3, 1, 6.0)
    assert summary.ops_per_second == 0.8
    assert summary.worst_second_p99_ms == 6.0, "the tick at t=10 is outside the window"


def test_a_stalled_second_is_one_where_an_operation_waited_half_a_second():
    ticks = [Tick(1.0, 0, 0, 0.0, STALL_MS), Tick(2.0, 5, 0, 1.0, STALL_MS - 1), Tick(3.0, 0, 0, 0.0, 3000.0)]
    assert summarize([], ticks, 0.0, 4.0).stalled_seconds == 2


def test_a_tick_belongs_to_the_window_its_midpoint_is_in():
    assert summarize([], [Tick(5.4, 0, 0, 9.0, 0.0)], 5.0, 6.0).worst_second_p99_ms == 0.0
    assert summarize([], [Tick(5.6, 0, 0, 9.0, 0.0)], 5.0, 6.0).worst_second_p99_ms == 9.0


def test_the_bar_is_twice_the_higher_baseline_and_needs_no_errors_and_no_stall():
    quiet = summarize([sample(0.5, 4.0)], [], 0.0, 1.0)
    noisy = summarize([sample(0.5, 8.0)], [], 0.0, 1.0)
    bar = Bar.bracketing(quiet, noisy)
    assert bar.baseline_p99_ms == 8.0
    assert bar.limit_ms == 16.0
    assert bar.allows(summarize([sample(0.5, 16.0)], [], 0.0, 1.0))
    assert not bar.allows(summarize([sample(0.5, 16.1)], [], 0.0, 1.0))


def test_an_error_or_a_stalled_second_fails_the_bar_even_with_a_low_p99():
    bar = Bar(10.0)
    assert not bar.allows(summarize([sample(0.5, 1.0, ok=False)], [], 0.0, 1.0))
    assert not bar.allows(summarize([sample(0.5, 1.0)], [Tick(1.0, 1, 0, 1.0, 900.0)], 0.0, 1.0))


@pytest.mark.parametrize("factor", [1.0, 3.0])
def test_the_factor_is_configurable(factor):
    assert Bar(10.0, factor).limit_ms == 10.0 * factor

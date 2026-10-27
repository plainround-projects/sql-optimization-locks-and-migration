from locks_lab.application.scenarios import SETTLE_SECONDS, Scenarios

from .fakes import FakeChanges, FakeFlip, FakeLoad, FakeLocks, FakeTable, window


def build(**options):
    changes, locks, pauses = FakeChanges(), FakeLocks(), list[float]()
    scenarios = Scenarios(
        table=FakeTable(), locks=locks, changes=changes, flip=FakeFlip(), pause=pauses.append, **options
    )
    return scenarios, changes, locks, pauses


def test_the_lock_queue_reports_the_snapshot_the_pile_up_window_and_the_recovery():
    scenarios, _changes, locks, _pauses = build()
    load = FakeLoad([window(3000.0, errors=5, stalled=6), window(4.0)])
    result = scenarios.lock_queue(load, hold_seconds=4)
    assert locks.holds == [4]
    assert result.during.p99_ms == 3000.0
    assert result.after.p99_ms == 4.0
    assert load.measured == [3], "three seconds of load after the long read is released"
    assert result.snapshot.request_of(391) is not None


def test_a_forced_conflict_waits_for_the_queue_it_joined_to_drain():
    scenarios, _changes, locks, pauses = build()
    assert scenarios.forced_conflict("1s").failed_fast
    assert locks.timeouts == ["1s"]
    assert pauses == [SETTLE_SECONDS]


def test_the_safe_migration_adds_the_column_then_backfills_and_counts_what_is_left():
    scenarios, changes, _locks, _pauses = build()
    result = scenarios.safe_migration(FakeLoad([window(10.0)]), batch_size=2000, pause_seconds=0.05)
    assert changes.calls == ["add_flagged_column", "backfill 2000 0.05"]
    assert (result.batches, result.add_column_attempts, result.rows_still_null) == (100, 1, 0)
    assert result.summary.p99_ms == 10.0


def test_a_stop_request_ends_the_backfill_without_error():
    scenarios, _changes, _locks, _pauses = build(should_stop=lambda: True)
    assert scenarios.safe_migration(FakeLoad(), 2000, 0.05).batches == 0


def test_the_plain_index_build_settles_before_the_window_is_read():
    scenarios, changes, _locks, pauses = build()
    result = scenarios.plain_index(FakeLoad([window(600.0, max_ms=600.0)]))
    assert changes.calls == ["plain_index_build"]
    assert (result.build_seconds, result.summary.max_ms) == (0.8, 600.0)
    assert pauses == [SETTLE_SECONDS]


def test_the_concurrent_index_is_interrupted_then_rebuilt_under_load():
    scenarios, changes, _locks, _pauses = build()
    result = scenarios.concurrent_index(FakeLoad())
    assert changes.calls == ["interrupted_concurrent_build", "rebuild_invalid_index"]
    assert result.interrupted.invalid_indexes == ("idx_events_device_created",)
    assert result.valid_after_rebuild


def test_the_naive_and_the_safe_not_null_are_measured_separately():
    scenarios, changes, _locks, _pauses = build()
    naive = scenarios.naive_not_null(FakeLoad())
    safe = scenarios.safe_not_null(FakeLoad())
    assert changes.calls == ["naive_set_not_null", "not_null_in_three_moves"]
    assert naive.report.seconds > 100 * safe.steps["set_not_null"].seconds
    assert safe.steps["validate"].lock_modes == ("ShareUpdateExclusiveLock",)


def test_the_plan_flip_parses_the_three_plans():
    result = build()[0].plan_flip()
    assert result.actual_rows == 150_000
    assert result.plans["f1_stale_statistics"].scans_everything
    assert result.plans["f3_after_extended_statistics"].estimate == 150_000


def test_the_table_size_comes_from_the_table():
    assert build()[0].table_size().pretty == "194 MB"

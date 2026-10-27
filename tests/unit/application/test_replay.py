import pytest

from locks_lab.application.replay import ReplayLesson
from locks_lab.application.scenarios import Scenarios
from locks_lab.domain.errors import LessonInterruptedError
from locks_lab.domain.host import HostLoad

from .fakes import FakeChanges, FakeFlip, FakeLoad, FakeLocks, FakeTable, RecordingStore, window


def build(windows=None, **options):
    table, store, changes = FakeTable(), RecordingStore(), FakeChanges()
    load = FakeLoad(windows)
    scenarios = Scenarios(table=table, locks=FakeLocks(), changes=changes, flip=FakeFlip(), pause=lambda _s: None)
    replay = ReplayLesson(
        load=load,
        table=table,
        scenarios=scenarios,
        store=store,
        baseline_seconds=60,
        closing_seconds=20,
        batch_size=2000,
        pause_seconds=0.05,
        **options,
    )
    return replay, load, table, store, changes


def test_the_steps_run_in_the_lessons_order():
    replay, _load, _table, _store, changes = build()
    replay.run()
    assert changes.calls == [
        "add_flagged_column",
        "backfill 2000 0.05",
        "plain_index_build",
        "interrupted_concurrent_build",
        "rebuild_invalid_index",
        "naive_set_not_null",
        "not_null_in_three_moves",
    ]


def test_every_step_is_marked_in_the_load_record():
    replay, load, *_ = build()
    replay.run()
    assert [mark.split(":")[0] for mark in load.marks] == [
        "reset to the seed's rows",
        "step 1",
        "step 2",
        "step 3",
        "step 4",
        "step 5",
        "step 6",
        "closing baseline",
    ]


def test_the_baseline_and_the_closing_baseline_are_measured_at_the_configured_lengths():
    replay, load, *_ = build()
    replay.run()
    assert load.measured[0] == 60
    assert load.measured[-1] == 20


def test_the_table_is_reset_before_the_lesson_and_after_each_experiment_that_leaves_something():
    replay, _load, table, *_ = build()
    replay.run()
    assert table.resets == 4


def test_the_lock_queue_and_the_plans_are_saved_beside_the_notes():
    replay, _load, _table, store, _changes = build()
    result = replay.run()
    assert "naive-alter" in store.texts["lock_queue.txt"]
    assert set(store.plans) == {"f1_stale_statistics", "f2_after_analyze", "f3_after_extended_statistics"}
    assert store.report is not None
    assert result.rows == 2_000_000


def test_the_bar_is_twice_the_higher_of_the_opening_and_closing_baselines():
    windows = [window(5.0)] + [window(1.0)] * 20 + [window(7.0)]
    replay, *_ = build(windows)
    result = replay.run()
    assert result.opening.p99_ms == 5.0
    assert result.bar.limit_ms == 2 * max(result.opening.p99_ms, result.closing.p99_ms)


def test_the_host_load_is_carried_into_the_notes():
    replay, _load, _table, store, _changes = build(host_load=HostLoad(40.0, 12))
    replay.run()
    assert store.report is not None
    assert "Measured on a loaded machine (load average 40.0 on 12 CPUs)" in store.report


def test_a_stop_request_ends_the_replay_before_the_next_step_without_notes():
    calls = []

    def should_stop() -> bool:
        calls.append(1)
        return len(calls) > 3

    replay, _load, _table, store, _changes = build(should_stop=should_stop)
    with pytest.raises(LessonInterruptedError):
        replay.run()
    assert store.report is None


def test_progress_is_reported_for_each_step():
    messages: list[str] = []
    replay, *_ = build(progress=messages.append)
    replay.run()
    assert "step 5: NOT NULL" in messages

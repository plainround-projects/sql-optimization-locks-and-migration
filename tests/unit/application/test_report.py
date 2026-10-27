from locks_lab.application.replay import ReplayLesson
from locks_lab.application.report import render_results
from locks_lab.application.scenarios import Scenarios
from locks_lab.domain.host import HostLoad

from .fakes import FakeChanges, FakeFlip, FakeLoad, FakeLocks, FakeTable, RecordingStore, window


def result(**options):
    table = FakeTable()
    scenarios = Scenarios(table=table, locks=FakeLocks(), changes=FakeChanges(), flip=FakeFlip(), pause=lambda _s: None)
    return ReplayLesson(
        load=FakeLoad(options.pop("windows", None)),
        table=table,
        scenarios=scenarios,
        store=RecordingStore(),
        baseline_seconds=60,
        batch_size=2000,
        pause_seconds=0.05,
        **options,
    ).run()


def test_the_windows_table_has_a_row_per_step_with_the_verdict():
    text = render_results(result())
    assert "| 1 baseline, opening |" in text
    assert "| 2 naive ALTER behind a long read (6 s) |" in text
    assert "| 5 NOT NULL in three moves |" in text


def test_a_window_within_the_bar_is_marked_yes_and_one_without_is_marked_no():
    windows = [window(5.0)] + [window(100.0, errors=3)] + [window(5.0)] * 20
    text = render_results(result(windows=windows))
    assert any(line.startswith("| 2 naive") and line.endswith("| no |") for line in text.splitlines())
    assert any(line.startswith("| 1 baseline, opening") and line.endswith("| yes |") for line in text.splitlines())


def test_the_lock_queue_the_bloat_and_the_not_null_table_are_in_the_notes():
    text = render_results(result())
    assert "waited 6.0 s for a read-only transaction" in text
    assert "table 194 MB before, 357 MB after the backfill (1,368,325 dead row versions)" in text
    assert "| validate | `VALIDATE CONSTRAINT` | ShareUpdateExclusiveLock | 140.0 |" in text


def test_the_plan_flip_table_shows_the_estimate_against_the_actual_rows():
    text = render_results(result())
    assert "| Before statistics catch up | 1 (filtered scan node) | 150,000 | Sort / Seq Scan | 175.0 |" in text


def test_a_quiet_machine_gets_the_plain_load_line_and_a_loaded_one_the_warning():
    assert "Measured at load average 2.0 on 12 CPUs." in render_results(result(host_load=HostLoad(2.0, 12)))
    assert "rerun `make run` on a quiet machine" in render_results(result(host_load=HostLoad(40.0, 12)))
    assert "Measured" not in render_results(result())

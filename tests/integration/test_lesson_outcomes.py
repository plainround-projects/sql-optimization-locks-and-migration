"""One test per "Done when" line of the lesson, against the seeded database with the load running (make up db first)."""

import pathlib
import threading
import time

import psycopg
import pytest

from locks_lab.domain.flip import parse_flip_plan
from locks_lab.domain.stats import Bar
from locks_lab.infrastructure.sql_script import run_file

from .conftest import bracket

pytestmark = pytest.mark.integration

SQL = pathlib.Path(__file__).resolve().parents[2] / "sql"


def test_step1_the_load_holds_a_steady_rate_with_stable_p99(load):
    windows = [load.measure(4) for _ in range(3)]
    assert all(w.errors == 0 and w.stalled_seconds == 0 for w in windows)
    assert all(w.ops_per_second >= 0.8 * 120 for w in windows), "the rate holds near 120 operations a second"
    p99s = sorted(w.p99_ms for w in windows)
    assert p99s[-1] <= 5 * max(p99s[1], 1.0), "no window's p99 is out of line with the others"


def test_step2_the_alter_waits_behind_a_long_read_and_the_load_waits_behind_the_alter(load, scenarios):
    result = scenarios.lock_queue(load, hold_seconds=4)
    snapshot = result.snapshot
    reader = next(request for request in snapshot.queue if request.application == "long-transaction")
    alter = snapshot.waiting_application("naive-alter")[0]
    assert reader.granted
    assert reader.mode == "AccessShareLock"
    assert alter.blocked_by == (reader.pid,), "the ALTER waits for the read-only transaction"
    alter_request = snapshot.request_of(alter.pid)
    assert alter_request is not None
    assert (alter_request.mode, alter_request.granted) == ("AccessExclusiveLock", False), "it never held its lock"
    behind_alter = snapshot.waiting_application("load")
    assert behind_alter
    assert all(session.blocked_by == (alter.pid,) for session in behind_alter), (
        "every load query waits for the ALTER, not for the read it has nothing to do with"
    )
    assert result.alter_seconds >= 3.5, "the ALTER did not run until the read ended"
    assert result.during.stalled_seconds >= 2
    assert result.during.ops_per_second < 12
    assert result.during.p99_ms >= 1000


def test_step3_the_safe_migration_keeps_p99_within_twice_baseline_and_a_forced_conflict_fails_fast(
    load, scenarios, connection, settings
):
    def relfilenode() -> int:
        return int(connection.execute("SELECT relfilenode FROM pg_class WHERE oid = 'events'::regclass").fetchone()[0])

    before_file = relfilenode()

    def migrate_safely():
        conflict = scenarios.forced_conflict("1s")
        return conflict, scenarios.safe_migration(load, settings.migration.batch_size, settings.migration.pause_seconds)

    before, (conflict, safe), after = bracket(load, migrate_safely)
    bar = Bar.bracketing(before, after)
    assert conflict.failed_fast
    assert 0.9 <= conflict.seconds < 2.5, "it gave up at lock_timeout instead of queueing"
    assert relfilenode() == before_file, "adding the column rewrote nothing"
    assert safe.summary.errors == 0
    assert safe.summary.stalled_seconds == 0
    assert safe.summary.p99_ms <= bar.limit_ms, f"p99 {safe.summary.p99_ms} ms against a bar of {bar.limit_ms} ms"
    assert safe.rows_still_null == 0
    assert safe.batches >= 50
    default = connection.execute(
        "SELECT column_default FROM information_schema.columns WHERE table_name = 'events' AND column_name = 'flagged'"
    ).fetchone()
    assert default is not None
    assert default[0] == "false", "rows inserted during the migration got a value from the default"


def test_step3_a_failed_attempt_retries_instead_of_giving_up(changes, settings):
    from locks_lab.infrastructure.postgres import connect

    long_read = connect(settings.postgres, autocommit=False, application_name="long-transaction")
    long_read.execute("SELECT * FROM events WHERE id = 1").fetchall()
    release = threading.Timer(3.0, long_read.rollback)  # after the first attempt's 2 s lock_timeout
    release.start()
    try:
        attempts = changes.apply(1)
    finally:
        release.join()
        long_read.close()
    assert attempts >= 2, "the first try hit lock_timeout; a retry after the read ended succeeded"


def test_step4_a_plain_index_build_stalls_writes_and_a_concurrent_one_does_not(load, scenarios):
    plain = scenarios.plain_index(load)
    time.sleep(2)
    concurrent = scenarios.concurrent_index(load)
    assert plain.summary.max_ms >= 0.5 * plain.build_seconds * 1000, "inserts waited for the whole build"
    assert concurrent.summary.errors == 0
    # Compared with the build's own length, not with the plain build: a loaded machine slows both builds, and the
    # question is whether any insert waited for the build.
    assert concurrent.summary.max_ms < 0.5 * concurrent.build_seconds * 1000, "writes kept flowing during the build"


def test_step4_an_interrupted_concurrent_build_leaves_an_invalid_index_that_is_found_and_dropped(changes, connection):
    interrupted = changes.interrupted_concurrent_build()
    assert interrupted.cancelled
    assert interrupted.invalid_indexes == ("idx_events_device_created",)
    assert interrupted.ready_but_invalid, "it is maintained on every write but no query can use it"
    assert connection.execute("SELECT pg_relation_size('idx_events_device_created')").fetchone()[0] > 0
    rebuilt = changes.rebuild_invalid_index()
    assert rebuilt.valid
    assert changes.invalid_indexes() == []


def test_step5_not_null_in_three_moves_holds_each_lock_only_briefly(settings, changes, scenarios):
    from locks_lab.infrastructure.load_runner import ThreadedLoad

    changes.add_flagged_column()
    changes.backfill_flagged(500_000, 0, lambda: False)  # no load yet: just prepare the column
    with ThreadedLoad(settings.postgres, settings.load) as running:
        running.measure(3)
        naive = scenarios.naive_not_null(running)
        safe = scenarios.safe_not_null(running)
    moves = safe.steps
    assert moves["add_check_not_valid"].lock_modes == ("AccessExclusiveLock",)
    assert moves["add_check_not_valid"].seconds < 0.5
    assert moves["validate"].lock_modes == ("ShareUpdateExclusiveLock",), "reads and writes continue during the scan"
    assert moves["set_not_null"].lock_modes == ("AccessExclusiveLock",)
    assert moves["set_not_null"].seconds < 0.5
    assert naive.report.seconds > 5 * moves["set_not_null"].seconds, "without the validated CHECK it scans the table"
    assert safe.summary.errors == 0
    assert safe.summary.stalled_seconds == 0
    assert safe.summary.max_ms < 500


def test_step5_the_column_ends_not_null_and_the_helper_constraint_is_gone(settings, changes, connection):
    changes.add_flagged_column()
    changes.backfill_flagged(500_000, 0, lambda: False)
    changes.not_null_in_three_moves()
    assert connection.execute(
        "SELECT attnotnull FROM pg_attribute WHERE attrelid = 'events'::regclass AND attname = 'flagged'"
    ).fetchone()[0]
    assert (
        connection.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'flagged_not_null'").fetchone()[0] == 0
    )


def test_step6_a_plan_flips_on_stale_statistics_and_is_fixed_by_extended_statistics(scenarios, connection):
    flip = scenarios.plan_flip()
    stale, analyzed, extended = (flip.plans[name] for name in sorted(flip.plans))
    assert flip.actual_rows == 150_000
    assert stale.estimate * 1000 < flip.actual_rows, "the planner expected one row"
    assert stale.scans_everything
    assert analyzed.estimate * 2 < flip.actual_rows, "ANALYZE still multiplies region by city as if independent"
    assert analyzed.walks_the_index
    assert abs(extended.estimate - flip.actual_rows) <= 0.1 * flip.actual_rows, "extended statistics know the pair"
    assert stale.milliseconds > 20 * extended.milliseconds
    kinds = connection.execute("SELECT kinds FROM pg_stats_ext WHERE statistics_name = 'events_region_city'").fetchone()
    assert kinds is not None
    assert sorted(kinds[0]) == ["f", "m"], "functional dependencies and mcv"
    assert parse_flip_plan(flip.lines["f3_after_extended_statistics"]).estimate == extended.estimate


def test_migrations_run_twice_and_revert_twice_in_reverse_order_without_harm(changes, connection):
    small = {"first_id": 1, "last_id": 5000}
    changes.apply(1)
    changes.apply(1)
    changes.backfill_flagged(500_000, 0, lambda: False)
    changes.apply(2, small)
    changes.apply(2, small)
    for number in (3, 4, 5, 6):
        changes.apply(number)
        changes.apply(number)
    assert changes.unflagged_rows() == 0
    assert (
        connection.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'flagged_not_null'").fetchone()[0] == 0
    )
    for number in (6, 5, 4, 3):
        changes.apply(number, down=True)
        changes.apply(number, down=True)
    changes.apply(2, small, down=True)
    changes.apply(2, small, down=True)
    assert changes.unflagged_rows() == 5000, "the down script of the backfill puts NULL back in its range"
    for _ in range(2):
        changes.apply(1, down=True)
    columns = {
        row[0]
        for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'events'")
    }
    assert "flagged" not in columns
    assert changes.invalid_indexes() == []


def test_the_schema_and_seed_scripts_can_run_twice(connection):
    run_file(connection, SQL / "001_schema.sql")
    run_file(connection, SQL / "001_schema.sql")
    assert connection.execute("SELECT count(*) FROM events").fetchone()[0] > 0
    seed = (SQL / "002_seed.sql").read_text()
    assert "\\if :events_empty" in seed


def test_the_lab_resets_to_the_seed(table, connection):
    table.reset()
    seed_rows = connection.execute("SELECT value FROM lab_meta WHERE key = 'seed_max_id'").fetchone()[0]
    assert table.row_count() == seed_rows
    columns = {
        row[0]
        for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'events'")
    }
    assert not columns & {"flagged", "scratch", "conflict_probe"}
    indexes = {row[0] for row in connection.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'events'")}
    assert indexes == {"events_pkey", "idx_events_created_at"}


def test_a_database_that_cannot_be_reached_is_reported_by_a_named_error(settings):
    import dataclasses

    from locks_lab.application.health import ProbeFailedError
    from locks_lab.infrastructure.health_probes import PostgresEventsProbe

    unreachable = dataclasses.replace(settings.postgres, port=1, connect_timeout_seconds=1)
    with pytest.raises(ProbeFailedError, match="cannot query PostgreSQL"):
        PostgresEventsProbe(unreachable).check()
    assert psycopg  # the failure is a PostgreSQL error wrapped in the named one

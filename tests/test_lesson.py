"""One test per "Done when" line of the lesson. They run against the compose database after `make db`,
with the load script running, so every number here is measured on a table that is being used."""
import threading
import time

from app import db, migrate, scenarios
from app.load import LoadRunner

BASELINE_SECONDS = 8


def bracket_baseline(runner, middle):
    """Baseline p99 around a change: measured before and after, the higher one counts.

    Other work on the machine moves p99 as much as a migration does, so the bar is twice the noisier of the two.
    """
    before = runner.measure(BASELINE_SECONDS)
    result = middle()
    after = runner.measure(BASELINE_SECONDS)
    return max(before["p99_ms"], after["p99_ms"]), result


def test_step1_the_load_holds_a_steady_rate_with_stable_p99(runner):
    windows = [runner.measure(4) for _ in range(3)]
    assert all(window["errors"] == 0 and window["stalled_seconds"] == 0 for window in windows)
    assert all(window["ops_per_second"] >= 0.8 * 120 for window in windows), "the rate holds near 120 operations a second"
    p99s = sorted(window["p99_ms"] for window in windows)
    assert p99s[-1] <= 5 * max(p99s[1], 1.0), "no window's p99 is out of line with the others"


def test_step2_the_alter_waits_behind_a_long_read_and_the_load_waits_behind_the_alter(runner):
    queue = scenarios.lock_queue(runner, hold_seconds=4)
    waiting, locks = queue["state"]["waiting"], queue["state"]["queue"]
    long_read = next(row for row in locks if row["application_name"] == "long-transaction")
    alter = next(row for row in waiting if row["application_name"] == "naive-alter")
    assert long_read["granted"] and long_read["mode"] == "AccessShareLock"
    assert alter["blocked_by"] == [long_read["pid"]], "the ALTER waits for the read-only transaction"
    alter_request = next(row for row in locks if row["pid"] == alter["pid"])
    assert alter_request["mode"] == "AccessExclusiveLock" and not alter_request["granted"], "it never held its lock"
    behind_alter = [row for row in waiting if row["application_name"] == "load"]
    assert behind_alter and all(row["blocked_by"] == [alter["pid"]] for row in behind_alter), \
        "every load query waits for the ALTER, not for the read it has nothing to do with"
    assert queue["alter_seconds"] >= 3.5, "the ALTER did not run until the read ended"
    assert queue["during"]["stalled_seconds"] >= 2 and queue["during"]["ops_per_second"] < 12
    assert queue["during"]["p99_ms"] >= 1000


def test_step3_safe_migration_keeps_p99_within_twice_baseline_and_a_forced_conflict_fails_fast(lab, runner):
    relfilenode = lambda: lab.execute("SELECT relfilenode FROM pg_class WHERE oid = 'events'::regclass").fetchone()[0]
    before_file = relfilenode()

    def migrate_safely():
        conflict = scenarios.forced_conflict(lock_timeout="1s")
        return conflict, scenarios.safe_add_column_and_backfill(runner, lab)

    bar, (conflict, safe) = bracket_baseline(runner, migrate_safely)
    assert conflict["failed_fast"] and 0.9 <= conflict["seconds"] < 2.5, "it gave up at lock_timeout instead of queueing"
    assert relfilenode() == before_file, "adding the column rewrote nothing"
    window = safe["summary"]
    assert window["errors"] == 0 and window["stalled_seconds"] == 0
    assert window["p99_ms"] <= 2 * bar, f"p99 {window['p99_ms']} ms against a bar of {2 * bar} ms"
    assert safe["rows_still_null"] == 0 and safe["batches"] >= 50
    default = lab.execute("SELECT column_default FROM information_schema.columns "
                          "WHERE table_name = 'events' AND column_name = 'flagged'").fetchone()[0]
    assert default == "false", "rows inserted during the migration got a value from the default"


def test_step3_a_failed_attempt_retries_instead_of_giving_up(lab):
    long_read = scenarios.hold_long_read()
    release = threading.Timer(3.0, long_read.rollback)       # after the first attempt's 2 s lock_timeout
    release.start()
    try:
        attempts, seconds = migrate.apply_with_retry(lab, db.migration(1), attempts=6, backoff_seconds=0.5)
    finally:
        release.join()
        long_read.close()
    assert attempts >= 2 and seconds < 10, "the first try hit lock_timeout; a retry after the read ended succeeded"


def test_step4_a_plain_index_build_stalls_writes_and_a_concurrent_one_does_not(lab, runner):
    plain = scenarios.plain_index_blocks_writes(runner, lab)
    time.sleep(2)
    concurrent = scenarios.concurrent_index(runner, lab)
    assert plain["summary"]["max_ms"] >= 0.5 * plain["build_seconds"] * 1000, "inserts waited for the whole build"
    assert concurrent["summary"]["errors"] == 0
    assert concurrent["summary"]["max_ms"] < plain["summary"]["max_ms"] / 3, "writes kept flowing during the concurrent build"


def test_step4_an_interrupted_concurrent_build_leaves_an_invalid_index_that_is_found_and_dropped(lab):
    interrupted = migrate.build_index_and_interrupt(lab)
    assert interrupted["cancelled"] and interrupted["invalid"] == ["idx_events_device_created"]
    assert interrupted["ready_but_invalid"], "it is maintained on every write but no query can use it"
    assert lab.execute("SELECT pg_relation_size('idx_events_device_created')").fetchone()[0] > 0
    migrate.drop_invalid_and_rebuild(lab)
    assert migrate.invalid_indexes(lab) == []
    assert lab.execute("SELECT indisvalid AND indisready FROM pg_index "
                       "WHERE indexrelid = 'idx_events_device_created'::regclass").fetchone()[0]


def test_step5_not_null_in_three_moves_holds_each_lock_only_briefly(lab):
    migrate.apply_with_retry(lab, db.migration(1))
    migrate.backfill_flagged(lab, batch_size=500_000, pause_seconds=0)          # no load yet: just prepare the column
    with LoadRunner() as runner:
        runner.measure(3)
        naive = scenarios.naive_set_not_null(runner, lab)
        safe = scenarios.safe_not_null(runner, lab)
    moves = safe["steps"]
    assert moves["add_check_not_valid"]["lock_modes"] == ["AccessExclusiveLock"] and moves["add_check_not_valid"]["seconds"] < 0.5
    assert moves["validate"]["lock_modes"] == ["ShareUpdateExclusiveLock"], "reads and writes continue during the scan"
    assert moves["set_not_null"]["lock_modes"] == ["AccessExclusiveLock"] and moves["set_not_null"]["seconds"] < 0.5
    assert naive["report"]["seconds"] > 5 * moves["set_not_null"]["seconds"], "without the validated CHECK it scans the table"
    assert safe["summary"]["errors"] == 0 and safe["summary"]["stalled_seconds"] == 0 and safe["summary"]["max_ms"] < 500
    assert lab.execute("SELECT attnotnull FROM pg_attribute WHERE attrelid = 'events'::regclass AND attname = 'flagged'").fetchone()[0]
    assert lab.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'flagged_not_null'").fetchone()[0] == 0


def test_step6_a_plan_flips_on_stale_statistics_and_is_fixed_by_extended_statistics(lab):
    flip = scenarios.plan_flip(lab)
    stale, analyzed, extended = (scenarios.plan_numbers(flip["plans"][name]) for name in (
        "f1_stale_statistics", "f2_after_analyze", "f3_after_extended_statistics"))
    actual = flip["actual_rows"]
    assert actual == 150_000
    assert stale["estimate"] * 1000 < actual and "Seq Scan" in stale["nodes"], "the planner expected one row and scanned everything"
    assert analyzed["estimate"] * 2 < actual and "Index Scan Backward" in analyzed["nodes"], \
        "ANALYZE fixes the plan but still multiplies region by city as if they were independent"
    assert abs(extended["estimate"] - actual) <= 0.1 * actual, "extended statistics know the pair"
    assert stale["milliseconds"] > 20 * extended["milliseconds"]
    kinds = lab.execute("SELECT kinds FROM pg_stats_ext WHERE statistics_name = 'events_region_city'").fetchone()[0]
    assert sorted(kinds) == ["f", "m"], "functional dependencies and mcv"


def test_the_lab_resets_to_the_seed(connection):
    scenarios.reset_lab(connection)
    seed_rows = connection.execute("SELECT value FROM lab_meta WHERE key = 'seed_max_id'").fetchone()[0]
    assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == seed_rows
    columns = {row[0] for row in connection.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'events'")}
    assert not columns & {"flagged", "scratch", "conflict_probe"}
    indexes = {row[0] for row in connection.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'events'")}
    assert indexes == {"events_pkey", "idx_events_created_at"}

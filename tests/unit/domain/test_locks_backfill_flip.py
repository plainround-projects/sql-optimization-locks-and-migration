import pytest

from locks_lab.domain.backfill import id_ranges
from locks_lab.domain.errors import PlanParseError
from locks_lab.domain.flip import parse_flip_plan
from locks_lab.domain.locks import LockRequest, LockSnapshot, WaitingSession

SNAPSHOT = LockSnapshot(
    waiting=(
        WaitingSession(391, "naive-alter", (390,), 3.0, "ALTER TABLE events ADD COLUMN flagged boolean"),
        WaitingSession(143, "load", (391,), 2.9, "INSERT INTO events"),
        WaitingSession(144, "load", (391,), 2.9, "INSERT INTO events"),
    ),
    queue=(
        LockRequest(390, "long-transaction", "AccessShareLock", True),
        LockRequest(391, "naive-alter", "AccessExclusiveLock", False),
        LockRequest(143, "load", "RowExclusiveLock", False),
    ),
)


def test_the_waiting_sessions_of_an_application_are_found_by_name():
    assert [session.pid for session in SNAPSHOT.waiting_application("load")] == [143, 144]
    assert SNAPSHOT.waiting_application("nobody") == ()


def test_the_lock_a_session_holds_or_waits_for_is_found_by_pid():
    request = SNAPSHOT.request_of(391)
    assert request is not None
    assert (request.mode, request.granted) == ("AccessExclusiveLock", False)
    assert SNAPSHOT.request_of(1) is None


def test_the_snapshot_prints_both_views_like_the_lessons_notes():
    text = SNAPSHOT.format()
    assert "pg_stat_activity, sessions waiting on a lock" in text
    assert "naive-alter" in text
    assert "[390]" in text
    assert "AccessExclusiveLock" in text
    assert text.endswith("\n")


def test_id_ranges_cover_every_id_once_with_the_last_batch_short():
    assert list(id_ranges(1, 10, 4)) == [(1, 4), (5, 8), (9, 10)]


def test_id_ranges_of_an_exact_multiple_and_of_nothing():
    assert list(id_ranges(1, 6, 3)) == [(1, 3), (4, 6)]
    assert list(id_ranges(5, 4, 3)) == []


def test_a_batch_size_below_one_is_refused():
    with pytest.raises(ValueError, match="at least 1"):
        list(id_ranges(1, 10, 0))


STALE = [
    "Limit  (cost=87147.68..87147.68 rows=1 width=16) (actual time=198.6..198.7 rows=100.00 loops=1)",
    "  ->  Sort  (cost=87147.68..87147.68 rows=1 width=16) (actual time=198.6..198.6 rows=100.00 loops=1)",
    "        ->  Seq Scan on events  (cost=0.00..87147.67 rows=1 width=16) (actual time=92.1..178.3 rows=150000.00)",
    "Execution Time: 198.721 ms",
]
FIXED = [
    "Limit  (cost=0.43..74.60 rows=100 width=16) (actual time=0.012..0.059 rows=100.00 loops=1)",
    "  ->  Index Scan Backward using idx_events_created_at on events  (cost=0.43..112563.55 rows=151757 width=16)",
    "Execution Time: 0.071 ms",
]


def test_a_stale_plan_reads_as_one_expected_row_and_a_scan_of_everything():
    plan = parse_flip_plan(STALE)
    assert plan.estimate == 1
    assert plan.nodes == ("Sort", "Seq Scan")
    assert plan.scans_everything
    assert not plan.walks_the_index
    assert plan.milliseconds == 198.721


def test_a_fixed_plan_walks_the_index_with_the_scan_nodes_estimate():
    plan = parse_flip_plan(FIXED)
    assert plan.estimate == 151757
    assert plan.walks_the_index
    assert not plan.scans_everything


def test_a_plan_without_analyze_is_refused():
    with pytest.raises(PlanParseError, match="ANALYZE"):
        parse_flip_plan(["Seq Scan on events  (cost=0.00..1.00 rows=1 width=1)"])

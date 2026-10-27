"""The lesson's experiments as functions, shared by scripts/run_lesson.py (long windows, writes the notes)
and by the tests (short windows, asserts). Each takes a running LoadRunner and returns plain data."""
import re
import threading
import time

from psycopg import errors

from app import db, locks, migrate

SETTLE_SECONDS = 2      # let operations that were blocked finish before a window is summarized


def reset_lab(connection):
    """Back to the baseline: no lesson column, index, constraint or statistics, and only the seed's rows."""
    connection.execute("SET lock_timeout = '5s'")
    for statement in ("DROP INDEX IF EXISTS idx_events_device_created", "DROP INDEX IF EXISTS idx_events_naive",
                      "ALTER TABLE events DROP CONSTRAINT IF EXISTS flagged_not_null",
                      "ALTER TABLE events DROP COLUMN IF EXISTS flagged", "ALTER TABLE events DROP COLUMN IF EXISTS scratch",
                      "ALTER TABLE events DROP COLUMN IF EXISTS conflict_probe",
                      "DROP STATISTICS IF EXISTS events_region_city"):
        migrate.apply_statement(connection, statement)
    connection.execute("DELETE FROM events WHERE id > (SELECT value FROM lab_meta WHERE key = 'seed_max_id')")
    connection.execute("ALTER TABLE events RESET (autovacuum_enabled)")
    connection.execute("VACUUM (ANALYZE) events")


def hold_long_read():
    """Session A: a transaction that has only read, left open. The caller rolls it back to release it."""
    connection = db.connect(autocommit=False, application_name="long-transaction")
    connection.execute("SELECT * FROM events WHERE id = 1").fetchall()
    return connection


def lock_queue(runner, hold_seconds=6):
    """Step 2: a long read, then a naive ALTER behind it. Returns what the lock views showed and what the load felt."""
    connection = db.connect()
    long_transaction = hold_long_read()
    outcome = {}

    def naive_alter():
        with db.connect(application_name="naive-alter") as alter_connection:
            started = time.perf_counter()
            alter_connection.execute("ALTER TABLE events ADD COLUMN flagged boolean")
            outcome["alter_seconds"] = time.perf_counter() - started

    alter_thread = threading.Thread(target=naive_alter)
    start = runner.now()
    alter_thread.start()
    time.sleep(hold_seconds / 2)
    state = locks.snapshot(connection)                   # the queue as it stands, mid-pile-up
    time.sleep(hold_seconds / 2)
    during = runner.summary(start, runner.now())
    long_transaction.rollback()
    long_transaction.close()
    alter_thread.join()
    after = runner.measure(3)
    connection.close()
    return {"state": state, "text": locks.format_snapshot(state), "during": during, "after": after,
            "alter_seconds": outcome["alter_seconds"], "hold_seconds": hold_seconds}


def forced_conflict(lock_timeout="1s"):
    """Step 3: a long read is open and the safe ALTER has a lock_timeout. It must fail fast, not queue."""
    long_transaction = hold_long_read()
    try:
        with db.connect(application_name="safe-alter") as connection:
            connection.execute(f"SET lock_timeout = '{lock_timeout}'")
            started = time.perf_counter()
            try:
                connection.execute("ALTER TABLE events ADD COLUMN conflict_probe boolean")
                failed = False
            except errors.LockNotAvailable:
                failed = True
            return {"failed_fast": failed, "seconds": time.perf_counter() - started}
    finally:
        long_transaction.rollback()
        long_transaction.close()
        time.sleep(SETTLE_SECONDS)                      # operations queued behind the failed ALTER finish first


def safe_add_column_and_backfill(runner, connection, batch_size=migrate.BACKFILL_BATCH, pause=migrate.BACKFILL_PAUSE_SECONDS):
    """Step 3: add the column with a lock_timeout, backfill in batches, and summarize the load meanwhile."""
    start = runner.now()
    started = time.perf_counter()
    attempts, _ = migrate.apply_with_retry(connection, db.migration(1))
    batches = migrate.backfill_flagged(connection, batch_size, pause)
    seconds = time.perf_counter() - started
    summary = runner.summary(start, runner.now())
    nulls = connection.execute("SELECT count(*) FROM events WHERE flagged IS NULL").fetchone()[0]
    return {"summary": summary, "seconds": seconds, "batches": batches, "add_column_attempts": attempts, "rows_still_null": nulls}


def plain_index_blocks_writes(runner, connection):
    """Step 4, the naive way: CREATE INDEX without CONCURRENTLY. Writes wait for the whole build."""
    start = runner.now()
    started = time.perf_counter()
    connection.execute("CREATE INDEX idx_events_naive ON events (device_id, created_at DESC)")
    build_seconds = time.perf_counter() - started
    time.sleep(SETTLE_SECONDS)
    summary = runner.summary(start, runner.now())
    connection.execute("DROP INDEX idx_events_naive")
    return {"build_seconds": build_seconds, "summary": summary}


def concurrent_index(runner, connection):
    """Step 4: interrupt a concurrent build on purpose, find the invalid index, drop it, rebuild while the load runs."""
    interrupted = migrate.build_index_and_interrupt(connection)
    start = runner.now()
    build_seconds = migrate.drop_invalid_and_rebuild(connection)
    time.sleep(SETTLE_SECONDS)
    summary = runner.summary(start, runner.now())
    valid = connection.execute(
        "SELECT indisvalid AND indisready FROM pg_index WHERE indexrelid = 'idx_events_device_created'::regclass").fetchone()[0]
    return {"interrupted": interrupted, "build_seconds": build_seconds, "summary": summary, "valid_after_rebuild": valid}


def naive_set_not_null(runner, connection):
    """Step 5, the naive way, on a scratch column: SET NOT NULL scans the table under ACCESS EXCLUSIVE."""
    connection.execute("ALTER TABLE events ADD COLUMN scratch boolean DEFAULT false")
    start = runner.now()
    report = migrate.run_with_lock_report(connection, ["ALTER TABLE events ALTER COLUMN scratch SET NOT NULL"])
    time.sleep(SETTLE_SECONDS)
    summary = runner.summary(start, runner.now())
    connection.execute("ALTER TABLE events DROP COLUMN scratch")
    return {"report": report, "summary": summary}


def safe_not_null(runner, connection):
    start = runner.now()
    steps = migrate.not_null_in_three_moves(connection)
    time.sleep(SETTLE_SECONDS)
    return {"steps": steps, "summary": runner.summary(start, runner.now())}


def plan_flip(connection):
    """Step 6: load a correlated month, plan before statistics catch up, after ANALYZE, after extended statistics."""
    connection.execute("SET max_parallel_workers_per_gather = 0")
    db.run_file(connection, db.SQL_DIR / "experiments" / "01_bulk_load_correlated_month.sql")
    actual = connection.execute("SELECT count(*) FROM events WHERE region = 'pacific' AND city = 'seattle'").fetchone()[0]
    plans = {}

    def capture(name):
        lines = [row[0] for row in db.run_file(connection, db.EXPLAIN_DIR / f"{name}.sql")]
        (db.EXPLAIN_DIR / f"{name}.txt").write_text("\n".join(lines) + "\n")
        plans[name] = lines

    capture("f1_stale_statistics")
    connection.execute("ANALYZE events")
    capture("f2_after_analyze")
    connection.execute("CREATE STATISTICS events_region_city (dependencies, mcv) ON region, city FROM events")
    connection.execute("ANALYZE events")
    capture("f3_after_extended_statistics")
    return {"actual_rows": actual, "plans": plans}


def plan_numbers(lines):
    """Planner estimate on the deepest node that filters, the plan's node types and its execution time."""
    text = "\n".join(lines)
    nodes = re.findall(r"^\s*(?:->\s*)?(Seq Scan|Index Scan Backward|Index Scan|Bitmap Heap Scan|Sort)\b", text, re.MULTILINE)
    estimates = re.findall(r"\(cost=[^)]*rows=(\d+)", text)
    return {"estimate": int(estimates[-1]), "nodes": " / ".join(dict.fromkeys(nodes)),
            "milliseconds": float(re.search(r"Execution Time: ([\d.]+) ms", text).group(1))}

# Changing a PostgreSQL table while it is in use

## What it is

A **migration** is a change to the structure of a database: a new column, a new index, a new rule. On a small table it takes a moment. On a table that is large and always in use, the *way* you change it decides whether the application keeps working. This note collects the techniques that let a table change without blocking its users: metadata-only changes, a batched backfill, a concurrent index build, and a constraint added in several moves. Together they follow the **expand and contract** pattern: first *expand* the structure so old and new code both work, then move the data, then *contract* by removing what is no longer needed.

## Why this repository uses it

This is the whole project. The lesson, "Change a huge busy table without blocking it", asks for three changes to a table that a load script keeps inserting into, updating and reading: add a column and backfill it, add an index, make the column `NOT NULL`. Each is done the naive way (to see the damage) and the safe way (to see it avoided), against the running load.

## Where it appears

| File | Change |
|---|---|
| `sql/migrations/001_add_flagged_column.sql` | Expand: the nullable column and its default. |
| `sql/migrations/002_backfill_flagged_batch.sql` | Backfill: one batch. |
| `sql/migrations/003_index_device_created_concurrently.sql` | The index, concurrently. |
| `sql/migrations/004_flagged_check_not_valid.sql`, `005_validate_flagged_check.sql`, `006_flagged_set_not_null.sql` | `NOT NULL` in three moves, then contract. |
| `sql/migrations/down/*.down.sql` | The way back for each. |
| `sql/naive/*.sql` | The three naive statements. |
| `src/locks_lab/infrastructure/schema_changes.py` | Runs the migration files and measures them. |
| `src/locks_lab/domain/backfill.py` | The id ranges of the backfill. |

## How it works underneath

**Metadata-only changes.** Some changes only edit the table's description and do not touch its rows, so they are instant whatever the size. `ALTER TABLE t ADD COLUMN c boolean` (nullable, no default) is one. Since PostgreSQL 11, adding a column with a constant default (`ADD COLUMN c boolean DEFAULT false`) is also instant: the default is stored in the catalog and returned for old rows. `ALTER COLUMN c SET DEFAULT x` changes only what future rows get. These still need a very brief `ACCESS EXCLUSIVE` lock, so they must not wait in line for it (see the locks note: use `lock_timeout` and retry).

**Backfill in batches.** When the new column's value is *derived* from existing data, old rows need an `UPDATE`. One `UPDATE` of every row would hold row locks on everything for a long time, write a huge burst of write-ahead log (WAL), and leave a copy of every row behind (see below). Instead: update `id BETWEEN a AND b AND c IS NULL` for ranges of a few thousand ids, each in its own short transaction, with a pause between batches. The `IS NULL` condition makes each batch safe to repeat. The batch size is a measurement: bigger batches finish sooner but each writes a bigger WAL burst that the application's commits wait behind; smaller batches are gentler.

**Dead rows (bloat).** An `UPDATE` in PostgreSQL does not change a row in place; it writes a new version and leaves the old one as a *dead tuple* until `VACUUM` removes it. A backfill that updates every row can double the table's size. `VACUUM` makes the space reusable inside the table, but does not return it to the operating system.

**Creating an index without blocking writes.** `CREATE INDEX` takes a `SHARE` lock: writes wait for the whole build. `CREATE INDEX CONCURRENTLY` takes `SHARE UPDATE EXCLUSIVE`, which writes do not conflict with. It costs: it reads the table twice, waits for every transaction that was open when it started, takes longer, and **cannot run inside a transaction block**. If it is cancelled or fails, it leaves an **invalid** index behind: the index exists, is kept up to date by every write, but is not used by queries (`indisvalid = false` in `pg_index`). It must be dropped (`DROP INDEX CONCURRENTLY`) and the build repeated. `CREATE INDEX CONCURRENTLY IF NOT EXISTS` would skip over the invalid leftover, so the leftover is dropped first.

**NOT NULL in three moves.** `ALTER TABLE t ALTER COLUMN c SET NOT NULL` normally scans the whole table under `ACCESS EXCLUSIVE` to verify there is no NULL. The way around:

1. `ALTER TABLE t ADD CONSTRAINT c_not_null CHECK (c IS NOT NULL) NOT VALID;` — brief `ACCESS EXCLUSIVE`; checks **new** writes from now on, does not look at existing rows.
2. `ALTER TABLE t VALIDATE CONSTRAINT c_not_null;` — scans the table under `SHARE UPDATE EXCLUSIVE`, which allows reads and writes.
3. `ALTER TABLE t ALTER COLUMN c SET NOT NULL;` — since PostgreSQL 12, if a valid CHECK constraint already proves the column is never NULL, PostgreSQL skips the scan, so the `ACCESS EXCLUSIVE` lock is brief. Then drop the now-redundant CHECK.

**Idempotent and reversible scripts.** Each migration is written to be safe to run twice (`IF NOT EXISTS`, `IF EXISTS`, a guard in a `DO` block for statements that have no `IF NOT EXISTS`, `WHERE c IS NULL` in a backfill) and has a **down script** that undoes it. A migration that cannot be undone says so in its down script.

**`SET LOCAL lock_timeout`.** Inside `BEGIN ... COMMIT`, `SET LOCAL` changes a setting only until the transaction ends.

## Walkthrough of this repository's use

### The new column: expand

`sql/migrations/001_add_flagged_column.sql`, lines 1 to 8:

```sql
-- Step 3, expand: a nullable column and a default for new rows. Both are metadata-only (no table rewrite),
-- and the lock_timeout makes the statement give up instead of queueing behind a long transaction.
-- Safe to run twice. Undo: down/001_add_flagged_column.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events ADD COLUMN IF NOT EXISTS flagged boolean;
ALTER TABLE events ALTER COLUMN flagged SET DEFAULT false;
COMMIT;
```

`BEGIN; SET LOCAL lock_timeout = '2s'; ... COMMIT;` (locks note). `ALTER TABLE events ADD COLUMN IF NOT EXISTS flagged boolean;` adds the nullable column: metadata only, no rewrite (the integration test checks that the table's file, `relfilenode` in `pg_class`, is the same before and after). `ALTER TABLE events ALTER COLUMN flagged SET DEFAULT false;` makes **new** rows get `false`, so rows inserted by the load while the backfill runs never need backfilling. `IF NOT EXISTS` makes the file safe to run twice. Its down script drops the column (`DROP COLUMN IF EXISTS`, also metadata-only).

### The backfill

`sql/migrations/002_backfill_flagged_batch.sql`, lines 1 to 9:

```sql
-- Step 3, backfill: one batch. The application runs it for id ranges with a pause between batches.
-- The value is derived from existing data, which is why a backfill is needed at all (a constant default
-- would need none in PostgreSQL 11 and later). Only rows still NULL are touched, so a batch can be repeated.
-- Run by hand: psql -v first_id=1 -v last_id=2000 < this file. Undo: down/002_backfill_flagged_batch.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
UPDATE events SET flagged = (event_type = 'error')
WHERE id BETWEEN :first_id AND :last_id AND flagged IS NULL;
COMMIT;
```

One batch: `UPDATE events SET flagged = (event_type = 'error') WHERE id BETWEEN :first_id AND :last_id AND flagged IS NULL;`. The new value is *derived* from existing data (true for `error` events), which is why a backfill is needed at all; the comment explains that a constant default would need none in PostgreSQL 11 and later. `:first_id` and `:last_id` are psql variables (the Python runner substitutes them, standard-library note). `AND flagged IS NULL` touches only rows not yet filled, so a batch can be repeated or the whole backfill restarted after an interruption.

`src/locks_lab/domain/backfill.py`, lines 1 to 15:

```python
"""The shape of a batched backfill: id ranges of a fixed size, so no single transaction touches the whole table."""

from __future__ import annotations

from collections.abc import Iterator


def id_ranges(first_id: int, last_id: int, batch_size: int) -> Iterator[tuple[int, int]]:
    """Inclusive (first, last) id ranges of `batch_size` ids from `first_id` up to and including `last_id`."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    start = first_id
    while start <= last_id:
        yield start, min(start + batch_size - 1, last_id)
        start += batch_size
```
`src/locks_lab/infrastructure/schema_changes.py`, lines 85 to 101:

```python
    def backfill_flagged(self, batch_size: int, pause_seconds: float, should_stop: Callable[[], bool]) -> int:
        """Fill `flagged` for the rows that exist now, `batch_size` ids at a time, pausing between batches.

        Rows inserted after the column was added already have a value (the default), so the range stops at the
        highest id seen when the backfill starts. Each batch only touches rows still NULL, so a stopped backfill can
        simply be started again. Stops between batches when `should_stop()` is true.
        """
        with session(self._settings, application_name="migration") as connection:
            last_id = int(scalar(connection, "SELECT max(id) FROM events"))
        batches = 0
        for first_id, last in id_ranges(1, last_id, batch_size):
            if should_stop():
                break
            self.apply(2, {"first_id": first_id, "last_id": last})
            batches += 1
            time.sleep(pause_seconds)
        return batches
```

The Python loop: read the highest id (`SELECT max(id) FROM events`), then for each range from `id_ranges(1, last_id, batch_size)` (2,000 ids at a time) run migration `002` through `apply(2, {"first_id": ..., "last_id": ...})` and `time.sleep(pause_seconds)` (0.05 s). Rows inserted after the column was added have the default already, so the range stops at the highest id seen when the backfill starts. `should_stop()` is checked before each batch: a stopped backfill leaves the rows done so far and can be started again. In the committed run: 1,013 batches, 83 seconds, 0 rows still NULL, 0 errors in the load, and the report shows the table at 194 MB before and 392 MB after, with 344,474 dead row versions left (the lab's note: "every updated row is a new version": the backfill updates every row once, so the table roughly doubles until a vacuum reuses the space). Batch size is a measurement, not a constant: [the ADR](docs/adr/0002-backfill-batch-size-is-a-measurement.md) explains why 2,000 and not the lesson's 10,000.

### The index, concurrently

`sql/migrations/003_index_device_created_concurrently.sql`, lines 1 to 5:

```sql
-- Step 4: build the lesson's index without blocking writes. Two table scans, cannot run in a transaction,
-- and an interrupted build leaves an INVALID index that must be dropped (see 003_queries.sql): IF NOT EXISTS
-- would skip over that leftover, so the application drops invalid indexes before it runs this file.
-- Undo: down/003_index_device_created_concurrently.down.sql.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_events_device_created ON events (device_id, created_at DESC);
```

`CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_events_device_created ON events (device_id, created_at DESC);`: cannot run in a transaction, so the file has no `BEGIN`; the comment says an interrupted build leaves an invalid index and that `IF NOT EXISTS` would skip it, so the application drops invalid indexes first.

`src/locks_lab/infrastructure/schema_changes.py`, lines 108 to 178:

```python
    def plain_index_build(self) -> float:
        with session(self._settings, application_name="naive-index") as connection:
            started = time.perf_counter()
            connection.execute("CREATE INDEX idx_events_naive ON events (device_id, created_at DESC)")
            seconds = time.perf_counter() - started
            connection.execute("DROP INDEX idx_events_naive")
        return seconds

    def invalid_indexes(self) -> list[str]:
        with session(self._settings) as connection:
            return [
                row[0]
                for row in connection.execute("SELECT indexrelid::regclass::text FROM pg_index WHERE NOT indisvalid")
            ]

    def interrupted_concurrent_build(self, phase: str = "index validation", attempts: int = 5) -> InterruptedBuild:
        """Start CREATE INDEX CONCURRENTLY in another session and cancel it once it reaches `phase`.

        Cancelled in its validation phase the index is already marked ready (so every write maintains it) but never
        became valid (so no query can use it). That is the leftover the lesson wants found. The build is quick on a
        small table, so a cancel that arrives too late is cleaned up and tried again.
        """
        path = migration_file(self._sql_dir, 3)
        cancelled = False
        with session(self._settings, application_name="lab-observer") as observer:
            for _ in range(attempts):
                outcome: dict[str, bool] = {}

                def build(outcome: dict[str, bool] = outcome) -> None:
                    with session(self._settings, application_name="index-build") as builder:
                        try:
                            run_file(builder, path)
                        except errors.QueryCanceled:
                            outcome["cancelled"] = True

                thread = threading.Thread(target=build, name="index-build")
                thread.start()
                while thread.is_alive():
                    row = observer.execute(
                        "SELECT pid FROM pg_stat_progress_create_index WHERE phase LIKE %s", (phase + "%",)
                    ).fetchone()
                    if row:
                        observer.execute("SELECT pg_cancel_backend(%s)", (row[0],))
                        break
                    time.sleep(0.01)
                thread.join()
                cancelled = outcome.get("cancelled", False)
                if cancelled:
                    break
                observer.execute(f"DROP INDEX IF EXISTS {DEVICE_INDEX}")  # finished before the cancel: try again
            state = observer.execute(
                f"SELECT indisvalid, indisready FROM pg_index WHERE indexrelid = to_regclass('{DEVICE_INDEX}')"
            ).fetchone()
        ready_but_invalid = state is not None and bool(state[1]) and not state[0]
        return InterruptedBuild(cancelled, tuple(self.invalid_indexes()), ready_but_invalid)

    def rebuild_invalid_index(self) -> RebuiltIndex:
        """Drop every invalid index (concurrently) and build the lesson's index again."""
        for name in self.invalid_indexes():
            with session(self._settings, application_name="migration") as connection:
                connection.execute(f"DROP INDEX CONCURRENTLY {name}")
        started = time.perf_counter()
        with session(self._settings, application_name="migration") as connection:
            run_file(connection, migration_file(self._sql_dir, 3))
            valid = bool(
                scalar(
                    connection,
                    f"SELECT indisvalid AND indisready FROM pg_index WHERE indexrelid = '{DEVICE_INDEX}'::regclass",
                )
            )
        return RebuiltIndex(time.perf_counter() - started, valid)
```

`plain_index_build` times a plain `CREATE INDEX` (the naive way) and drops it. `interrupted_concurrent_build` starts the concurrent build on a thread and cancels it when `pg_stat_progress_create_index` shows the phase "index validation" (threads note), then reads `pg_index`: `indisready` true (writes maintain it) and `indisvalid` false (queries cannot use it): `ready_but_invalid`. `invalid_indexes()` lists every row of `pg_index` with `NOT indisvalid`. `rebuild_invalid_index()` runs `DROP INDEX CONCURRENTLY` on each invalid index and then migration `003` again, and checks `indisvalid AND indisready`.

### NOT NULL in three moves

`sql/migrations/004_flagged_check_not_valid.sql`, lines 1 to 13:

```sql
-- Step 5, move 1: ACCESS EXCLUSIVE for a moment (metadata only). New writes are checked from now on;
-- existing rows are not looked at yet. ADD CONSTRAINT has no IF NOT EXISTS, so the DO block makes it repeatable.
-- Safe to run twice. Undo: down/004_flagged_check_not_valid.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'flagged_not_null' AND conrelid = 'events'::regclass) THEN
    ALTER TABLE events ADD CONSTRAINT flagged_not_null CHECK (flagged IS NOT NULL) NOT VALID;
  END IF;
END
$$;
COMMIT;
```

Move 1: add the check `NOT VALID`. `ADD CONSTRAINT` has no `IF NOT EXISTS`, so a `DO $$ ... $$` block (an anonymous block of PL/pgSQL, PostgreSQL's procedural language) checks `pg_constraint` first (`IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'flagged_not_null' AND conrelid = 'events'::regclass) THEN ... END IF;`), which makes the file repeatable.

`sql/migrations/005_validate_flagged_check.sql`, lines 1 to 4:

```sql
-- Step 5, move 2: the real scan, under SHARE UPDATE EXCLUSIVE, which allows reads, inserts, updates and deletes.
-- Validating an already validated constraint does nothing, so this is safe to run twice.
-- Undo: there is nothing to undo; down/005_validate_flagged_check.down.sql says so.
ALTER TABLE events VALIDATE CONSTRAINT flagged_not_null;
```
`sql/migrations/006_flagged_set_not_null.sql`, lines 1 to 8:

```sql
-- Step 5, move 3: ACCESS EXCLUSIVE for a moment. PostgreSQL sees the validated CHECK and skips the scan.
-- Contract: the CHECK is now redundant with the column's NOT NULL, so drop it.
-- Safe to run twice. Undo: down/006_flagged_set_not_null.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events ALTER COLUMN flagged SET NOT NULL;
ALTER TABLE events DROP CONSTRAINT IF EXISTS flagged_not_null;
COMMIT;
```

Move 2: `VALIDATE CONSTRAINT` (the scan, without blocking). Move 3: `SET NOT NULL` (instant because the validated check proves it) and then `DROP CONSTRAINT IF EXISTS flagged_not_null` (the contract step: the constraint is now redundant). Because `VALIDATE CONSTRAINT` is idempotent, `005` needs no guard. The down scripts: `006`'s down puts the check back (not yet validated) and drops NOT NULL; `005`'s down only prints that there is nothing to undo ("a constraint cannot be un-validated"; it points to `004`'s down, which drops the constraint).

`src/locks_lab/infrastructure/schema_changes.py`, lines 216 to 239:

```python
    def naive_set_not_null(self) -> LockReport:
        with session(self._settings) as connection:
            connection.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS scratch boolean DEFAULT false")
        report = self._report(["ALTER TABLE events ALTER COLUMN scratch SET NOT NULL"])
        with session(self._settings) as connection:
            connection.execute("ALTER TABLE events DROP COLUMN IF EXISTS scratch")
        return report

    def not_null_in_three_moves(self) -> dict[str, LockReport]:
        """The same three moves as migrations 004 to 006, each run in its own transaction so its locks can be read."""
        return {
            "add_check_not_valid": self._report(
                [
                    "ALTER TABLE events ADD CONSTRAINT flagged_not_null CHECK (flagged IS NOT NULL) NOT VALID",
                ]
            ),
            "validate": self._report(["ALTER TABLE events VALIDATE CONSTRAINT flagged_not_null"]),
            "set_not_null": self._report(
                [
                    "ALTER TABLE events ALTER COLUMN flagged SET NOT NULL",
                    "ALTER TABLE events DROP CONSTRAINT flagged_not_null",
                ]
            ),
        }
```

`naive_set_not_null` adds a scratch column with a default, then reports `SET NOT NULL` without any check (a full scan under `ACCESS EXCLUSIVE`: 187 ms in the committed run), then drops the column. `not_null_in_three_moves` runs the same three moves as the migration files, each in its own transaction so its locks can be read (3.6 ms, 158 ms, 1.2 ms).

### Running every migration twice, and undoing

The integration test `test_migrations_run_twice_and_revert_twice_in_reverse_order_without_harm` applies each migration twice, then each down script twice in reverse order, and checks the column, the constraint and the index are gone. `make db` twice changes nothing (the seed refuses to double-load).

## Try it yourself

(After `make up db`; `P="docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U lab -d lab"`.)

1. `$P < sql/migrations/001_add_flagged_column.sql` — adds the column (instant). Run it again: no error. `$P -c "\d events"` shows `flagged | boolean | | | false`.
2. Backfill one batch by hand: `$P -v first_id=1 -v last_id=2000 < sql/migrations/002_backfill_flagged_batch.sql`, then `$P -c "select count(*) filter (where flagged is null) as still_null, count(*) filter (where flagged) as flagged from events where id <= 2000"` — `still_null` is 0.
3. `$P < sql/migrations/003_index_device_created_concurrently.sql`, then `$P -c "select indexrelid::regclass, indisvalid, indisready from pg_index where indrelid = 'events'::regclass"` lists the indexes with their flags.
4. The three moves: `$P < sql/migrations/004_flagged_check_not_valid.sql`, then `$P -c "select conname, convalidated from pg_constraint where conrelid = 'events'::regclass"` shows `flagged_not_null | f`; after `005` it is `t`. (On the full table, 005 scans; the backfill must be complete first, otherwise it fails because some rows are still NULL.)
5. `make reset db` puts the lab back to the seed. `make run` replays everything against the load.

## Mistakes people make

- Running a table rewrite (`ALTER COLUMN ... TYPE`, adding a volatile default) on a big table without knowing it rewrites.
- A single `UPDATE` of the whole table.
- Forgetting that `CREATE INDEX CONCURRENTLY` can fail and leave an invalid index.
- `SET NOT NULL` directly on a big table.
- Retrying a migration with no pause and no `lock_timeout`.
- Dropping the old structure before every application instance uses the new one.

**How this repository avoids them.** Every migration is idempotent and has a down script; strong locks are taken under `lock_timeout` and retried; the backfill is batched, paused and restartable; the index is built concurrently with a cleanup for the invalid leftover; and `NOT NULL` is done in three moves so no scan happens under the strong lock.

## Check yourself

1. Why is `ADD COLUMN flagged boolean` instant? *It only changes the catalog; no row is rewritten.*
2. Why backfill in batches with a pause? *To keep each transaction short and each WAL burst small so the application's commits are not held up.*
3. What does an invalid index mean? *A concurrent build was interrupted: the index is maintained by writes but queries cannot use it; drop it and rebuild.*
4. Why does the second move of the NOT NULL change use a different lock? *`VALIDATE CONSTRAINT` takes `SHARE UPDATE EXCLUSIVE`, which allows reads and writes during the scan.*
5. What is "expand and contract"? *Add the new structure beside the old, switch over, then remove the old.*

## Further reading

- PostgreSQL 18, `ALTER TABLE` (notes on lock levels, `NOT VALID`, `VALIDATE CONSTRAINT`, `SET NOT NULL`): https://www.postgresql.org/docs/18/sql-altertable.html
- `CREATE INDEX` ("Building Indexes Concurrently"): https://www.postgresql.org/docs/18/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY
- Routine vacuuming: https://www.postgresql.org/docs/18/routine-vacuuming.html

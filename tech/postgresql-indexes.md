# PostgreSQL indexes

## What it is

An **index** is a second structure kept beside a table that lets the database find rows without reading the whole table, like the index at the back of a book. Without one, finding the rows with `customer_id = 7` means reading every page of the table (a **sequential scan**). With one, the database looks up `7` in a small sorted structure and goes straight to the matching rows.

## Why this repository uses it

Indexes appear in this lab in three roles: an index the load needs from the start (`idx_events_created_at`), an index built while the load runs (`idx_events_device_created`, the lesson's step 4), and the index whose use depends on the planner's estimate (the plan flip). The point is not which index helps a query, but what it costs to *build* one on a busy table.

## Where it appears

| File | Index |
|---|---|
| `sql/001_schema.sql` | `events_pkey (id)` and `idx_events_created_at (created_at)`. |
| `sql/migrations/003_index_device_created_concurrently.sql` | `idx_events_device_created (device_id, created_at DESC)`, built concurrently. |
| `sql/naive/02_create_index_blocking_writes.sql` | `idx_events_naive`, the plain build. |
| `sql/explain/f2_*.txt`, `f3_*.txt` | The plans that walk `idx_events_created_at` backwards. |
| `src/locks_lab/infrastructure/schema_changes.py` | Builds, cancels, finds and rebuilds. |

## How it works underneath

**B-tree.** The default index type is a **B-tree**: a balanced tree of 8 kB pages. The top page lists ranges of key values and points to pages below; the bottom pages (**leaf pages**) hold the keys in sorted order, each with a pointer (the row's physical address) to the row in the table. Finding one key takes only a handful of page reads, even for a million rows, because the tree is shallow. Because the leaves are sorted, a B-tree also answers range questions (`created_at >= x AND created_at < y`) by finding the start and reading forward, and it can return rows already in sorted order (so no separate sort step is needed).

**Multi-column indexes.** `(customer_id, created_at DESC)` sorts by `customer_id` first, and rows with the same customer by `created_at` newest first. All the rows of one customer therefore sit together, newest first. The index helps queries that fix the first column (equality) and then use the next (a range or an order). It does *not* help a query that only mentions `created_at`. The column order matters: equality columns first, then the range or sort column.

**Direction.** `DESC` stores that column in descending order, so "newest first" can be read from the start.

**Covering index (`INCLUDE`).** `CREATE INDEX ... (a, b) INCLUDE (c, d)` also stores `c` and `d` in the leaf pages, though they are not part of the sort key. A query that needs only `a, b, c, d` can be answered from the index alone: an **index-only scan**, which never visits the table. The catch: the index entry does not say whether the row is *visible* to the current transaction, so PostgreSQL consults the **visibility map**; if the page is marked all-visible it trusts the index, otherwise it visits the table page (a *heap fetch*). `VACUUM` keeps the visibility map current.

**Scan types you will see in plans.**

- `Seq Scan`: read the whole table.
- `Index Scan`: walk the index and fetch each matching row from the table in index order.
- `Index Only Scan`: answer from the index alone.
- `Bitmap Index Scan` + `Bitmap Heap Scan`: collect all matching row addresses from the index into a bitmap, sort them by page, then read each table page once. Used when many rows match.

**Why a function on the column blocks the index.** An index on `created_at` is sorted by `created_at`, not by `date(created_at)`. The condition `date(created_at) = '2026-03-14'` forces the database to compute the function for every row. Rewrite it as a range on the bare column: `created_at >= '2026-03-14' AND created_at < '2026-03-15'`. Conditions that an index can use are called **sargable** (search-argument-able).

**Costs.** An index takes disk space and slows every `INSERT`, `UPDATE` and `DELETE` (each change must update every index, and writes WAL for it). Add an index when a read is worth that cost; drop one that another index makes redundant: `(customer_id, created_at) INCLUDE (...)` has the same leading columns as `(customer_id, created_at)`, so it serves the same lookups.

**`CREATE INDEX IF NOT EXISTS`** makes creation safe to repeat. A plain `CREATE INDEX` blocks writes to the table while it builds; `CREATE INDEX CONCURRENTLY` does not (but cannot run inside a transaction and takes longer).

## Walkthrough of this repository's use

### The index the load needs

`sql/001_schema.sql`, lines 19 to 21:

```sql
-- The load script reads "recent events" with a predicate on created_at, so the table starts with this index.
-- The lesson's index (device_id, created_at DESC) is a migration, not part of the baseline.
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at);
```

The load reads `WHERE created_at >= now() - interval '1 minute' ORDER BY created_at DESC LIMIT 20`: a range on `created_at` read newest first, exactly what a B-tree on `created_at` gives (the leaf pages are sorted, so "the newest 20" are the last entries). Without it each read would scan 2,000,000 rows and the baseline would not be a few milliseconds. The same index is what the plan flip walks backwards (`Index Scan Backward using idx_events_created_at`): the planner reads rows in time order and stops after 100 matches.

### The lesson's index, built two ways

`sql/naive/02_create_index_blocking_writes.sql`, lines 1 to 3:

```sql
-- The naive index build of step 4: a plain CREATE INDEX holds a SHARE lock for the whole build, so inserts,
-- updates and deletes on events wait until it finishes. Reads still run.
CREATE INDEX IF NOT EXISTS idx_events_naive ON events (device_id, created_at DESC);
```
`sql/migrations/003_index_device_created_concurrently.sql`, lines 1 to 5:

```sql
-- Step 4: build the lesson's index without blocking writes. Two table scans, cannot run in a transaction,
-- and an interrupted build leaves an INVALID index that must be dropped (see 003_queries.sql): IF NOT EXISTS
-- would skip over that leftover, so the application drops invalid indexes before it runs this file.
-- Undo: down/003_index_device_created_concurrently.down.sql.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_events_device_created ON events (device_id, created_at DESC);
```

`(device_id, created_at DESC)`: all events of a device together, newest first (equality column first, then the sort column; the PostgreSQL-indexes ideas of the other labs). Built plainly it takes a `SHARE` lock: writes wait. Built `CONCURRENTLY` it takes `SHARE UPDATE EXCLUSIVE`: writes continue (locks note). Numbers from the committed run: plain build 0.8 s with the load held up (p99 691 ms, slowest operation 693 ms, 0 errors); concurrent build 1.0 s with 0 errors and a slowest operation of 130 ms. The concurrent build is slower because it scans the table twice and waits for old transactions.

### The invalid leftover

`src/locks_lab/infrastructure/schema_changes.py`, lines 123 to 178:

```python
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

A concurrent build goes through phases that `pg_stat_progress_create_index` reports (`building index: scanning table`, `building index: sorting`, `waiting for writers before validation`, `index validation: scanning index`, ...). The lab cancels it when the phase starts with "index validation", then looks in `pg_index`: `indisready` true (the index is maintained by every write from now on) and `indisvalid` false (queries will not use it). `\d events` shows it as `INVALID`. The cleanup: `DROP INDEX CONCURRENTLY` for each invalid index, then build again. The query for finding them (also in `sql/003_queries.sql`):

`sql/003_queries.sql`, lines 16 to 20:

```sql
-- Step 4: invalid indexes, the leftovers of an interrupted CREATE INDEX CONCURRENTLY (empty is good).
SELECT indexrelid::regclass AS invalid_index FROM pg_index WHERE NOT indisvalid;

-- Step 4: progress of a running index build (empty when none is running).
SELECT pid, phase, blocks_done, blocks_total, tuples_done, tuples_total FROM pg_stat_progress_create_index;
```

### The plan that depends on an index

See the statistics note: with the right estimates the planner uses `idx_events_created_at` backwards; with the wrong ones it ignores the index and scans the table.

## Try it yourself

(After `make up db`.)

1. `docker compose exec db psql -U lab -d lab -c "\d events"` — lists `events_pkey` and `idx_events_created_at`.
2. Build and measure the plain index: `docker compose exec db psql -U lab -d lab -c "\timing on" -c "create index idx_events_naive on events (device_id, created_at desc)" -c "drop index idx_events_naive"` — the create takes a few seconds for 2,000,000 rows (hundreds of ms on a fast machine); during it, `make load SECONDS=20` in another terminal shows the `ops` falling to zero.
3. Build the lesson's index concurrently: `docker compose exec -T db psql -X -q -U lab -d lab < sql/migrations/003_index_device_created_concurrently.sql`, then `docker compose exec db psql -U lab -d lab -c "select indexrelid::regclass, indisvalid, indisready from pg_index where indrelid = 'events'::regclass"` — all `t`/`t`.
4. Undo with `docker compose exec -T db psql -X -q -U lab -d lab < sql/migrations/down/003_index_device_created_concurrently.down.sql`.
5. `make run` and read the "Step 4" section of `sql/explain/results.md` for the invalid index it found.

## Mistakes people make

- Indexing every column "just in case".
- Putting a range column before an equality column in a multi-column index.
- Wrapping the indexed column in a function in the `WHERE` clause.
- Forgetting that an index must be maintained on every write.
- Expecting an index-only scan on a table that was never vacuumed.
- Keeping two indexes where one covers both.

**How this repository avoids them.** The concurrent build has a cleanup path for its invalid leftover (found by query, dropped concurrently, rebuilt), its file has no transaction block, and its down script is also concurrent.

## Check yourself

1. Why is a B-tree lookup fast even for a million rows? *The tree is shallow, so only a few pages are read to find one key.*
2. Why does `date(created_at) = '2026-03-14'` not use an index on `created_at`? *The index is sorted by the raw column, not by the function result; the database would have to compute the function for every row.*
3. In `(customer_id, created_at DESC)`, which queries are served? *Those that fix `customer_id` and then filter or order by `created_at`, newest first.*
4. What does `INCLUDE (id, status, total)` add? *The extra columns are stored in the leaf pages so a query needing only those columns can be answered without visiting the table.*
5. What does `Heap Fetches: 0` mean in an index-only scan? *Every page was marked all-visible, so no table page had to be visited.*

## Further reading

- PostgreSQL 18, "Indexes": https://www.postgresql.org/docs/18/indexes.html — "Index Types" (B-tree), "Multicolumn Indexes", "Indexes and ORDER BY", "Index-Only Scans and Covering Indexes" (https://www.postgresql.org/docs/18/indexes-index-only-scans.html).
- `CREATE INDEX`: https://www.postgresql.org/docs/18/sql-createindex.html

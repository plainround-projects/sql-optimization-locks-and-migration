# SQL

## What it is

**SQL** (Structured Query Language) is the language for talking to relational databases. You describe *what* you want ("the ten newest orders of customer 7") and the database decides *how* to get it. An SQL text is made of **statements** ended by semicolons. Keywords are not case-sensitive (`select` and `SELECT` are the same); the convention is to write them in capitals.

## Why this repository uses it

The lab is SQL. The table, the data, the inspection queries, every migration and its undo, the naive statements and the plan-flip load are SQL files you can read and run by hand. The Python code runs them, measures them, and reads the answers.

## Where it appears

| File | What it contains |
|---|---|
| `sql/001_schema.sql` | The `events` table, its index, comments, and `lab_meta`. |
| `sql/002_seed.sql` | The data generator (chunked, with psql commands). |
| `sql/003_queries.sql` | The inspection queries on the system views. |
| `sql/reset.sql` | Drops the lab's tables. |
| `sql/migrations/001` to `006` and `down/` | The safe changes and their undo. |
| `sql/naive/01` to `03` | The three statements that block. |
| `sql/experiments/01_bulk_load_correlated_month.sql` | The plan-flip load. |
| `sql/explain/*.sql` | The `EXPLAIN` statements. |

## How it works underneath

**Data definition (DDL):** statements that create or change structure.

- `CREATE TABLE name (column type constraints, ...)`: a new table. Constraints: `PRIMARY KEY` (unique, not null, indexed), `NOT NULL`.
- `CREATE INDEX name ON table (columns)`; `DROP INDEX name`; `DROP TABLE name`; `ALTER TABLE ...`.
- `COMMENT ON TABLE t IS 'text'` attaches a description stored in the database.
- `IF NOT EXISTS` / `IF EXISTS` make a statement do nothing instead of failing when the object already exists / is already gone. This makes scripts **idempotent**: safe to run twice.

**Queries and data changes (DML):**

- `SELECT columns FROM table WHERE condition GROUP BY columns ORDER BY column [DESC] LIMIT n`.
  - `WHERE` keeps rows for which the condition is true. `AND`, `OR`, `NOT`, `BETWEEN a AND b`, `=`, `<`, `>=`.
  - `GROUP BY` makes groups; aggregate functions summarise each group: `count(*)`, `max(x)`, `sum(x)`.
  - `ORDER BY` sorts (`DESC` is descending). `LIMIT n` keeps the first n rows.
  - `count(*) FILTER (WHERE condition)` counts only the rows meeting the condition.
  - `SELECT *` returns every column.
- `INSERT INTO table (columns) SELECT ... FROM generate_series(1, 1000000)`: inserts the rows a query produces. `generate_series(a, b)` produces the numbers a to b.
- `UPDATE`, `DELETE` change or remove rows.

**Expressions.** `x::int` converts the type (a **cast**). `CASE WHEN condition THEN a ELSE b END` chooses. `(ARRAY['a','b'])[2]` picks the second element of an array (counting starts at 1). `timestamp '2026-01-01' + n * interval '1 day'` adds a span of time. Text literals use single quotes; `''` inside means a quote. Double quotes name identifiers.

**Functions used here.** `random()` returns a decimal between 0 and 1; `floor(x)`; `round(x, 2)`; `repeat('ab', 3)` gives `ababab`; `md5(text)`; `string_agg(x, '')` joins text values; `date(timestamp)` extracts the date; `setseed(0.42)` makes `random()` repeatable.

**Transactions.** `BEGIN;` starts a group of statements, `COMMIT;` saves them all, `ROLLBACK;` throws them away.

**Maintenance and inspection statements.** `VACUUM`, `ANALYZE`, `EXPLAIN`, `SET timezone = 'UTC'` (change a session setting), `SHOW`.

**Comments.** `-- to end of line`. A statement ends at `;`.

**NULL** means "no value / unknown". `x = NULL` is never true; use `x IS NULL`. `NOT EXISTS (SELECT 1 FROM t)` is true when the table has no rows.

## Walkthrough of this repository's use

### `001_schema.sql`: structure

`sql/001_schema.sql`, lines 1 to 26:

```sql
-- 001_schema.sql: DDL for the "Locks and migration" lab (PostgreSQL 18). Safe to run twice: IF NOT EXISTS
-- throughout, one transaction.
BEGIN;

CREATE TABLE IF NOT EXISTS events (
  id         BIGSERIAL   PRIMARY KEY,
  device_id  BIGINT      NOT NULL,
  event_type TEXT        NOT NULL,
  region     TEXT        NOT NULL,
  city       TEXT        NOT NULL,
  payload    JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  events            IS 'The busy table: inserts, updates and reads never stop while the lab changes it.';
COMMENT ON COLUMN events.region     IS 'Seeded independently of city; the plan-flip experiment loads a month where the two are correlated.';
COMMENT ON COLUMN events.created_at IS 'Seed rows are September 2026; the load script adds rows stamped now().';

-- The load script reads "recent events" with a predicate on created_at, so the table starts with this index.
-- The lesson's index (device_id, created_at DESC) is a migration, not part of the baseline.
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at);

-- Where the seed ended, so the lab can delete everything the load and the experiments added.
CREATE TABLE IF NOT EXISTS lab_meta (key TEXT PRIMARY KEY, value BIGINT NOT NULL);

COMMIT;
```

- `BEGIN;` (line 3) to `COMMIT;` (line 26): one transaction, so the table, the index and `lab_meta` are created together or not at all.
- `CREATE TABLE IF NOT EXISTS events (...)`: `id BIGSERIAL PRIMARY KEY` (a 64-bit number from a sequence, the unique key); `device_id BIGINT NOT NULL`; `event_type`, `region` and `city` as `TEXT NOT NULL`; `payload JSONB` (may be empty); `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` (a moment in time; if an insert gives no value, it is the current time).
- `COMMENT ON TABLE/COLUMN ... IS '...'` store descriptions in the database.
- `CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at);` (the comment above explains why it exists from the start).
- `CREATE TABLE IF NOT EXISTS lab_meta (key TEXT PRIMARY KEY, value BIGINT NOT NULL);`: a two-column table for facts about the lab; one row remembers `seed_max_id`.

### `002_seed.sql`: data

`sql/002_seed.sql`, lines 1 to 12:

```sql
-- 002_seed.sql: DML. :rows events (default 2,000,000), analyzed, with region and city independent.
-- Safe to run twice: a table that already has rows is left alone (use `make reset` to start from nothing).
-- Run as: psql -v rows=50000000 < sql/002_seed.sql   (the lesson's size)
\if :{?rows}
\else
  \set rows 2000000
\endif
SELECT setseed(0.42);
SET timezone = 'UTC';

SELECT NOT EXISTS (SELECT 1 FROM events) AS events_empty \gset

```

- Lines 4 to 7: `\if :{?rows} ... \else \set rows 2000000 \endif`. These are **psql commands**, not SQL (psql note). `:{?rows}` is true if the psql variable `rows` is defined (`make db` passes `-v rows=$(ROWS)`); otherwise `\set rows 2000000` gives it a default.
- `SELECT setseed(0.42);` fixes the starting point of `random()` so the data is the same each run; `SET timezone = 'UTC';`.
- Line 11: `SELECT NOT EXISTS (SELECT 1 FROM events) AS events_empty \gset` computes true/false (is the table empty?) and `\gset` stores it in the psql variable `events_empty`.

`sql/002_seed.sql`, lines 13 to 37:

```sql
-- Loaded in chunks of 1,000,000 so a 50,000,000-row load does not need one huge transaction.
\if :events_empty
SELECT format($sql$
  INSERT INTO events (device_id, event_type, region, city, payload, created_at)
  SELECT 1 + floor(random() * 100000)::bigint,
         (ARRAY['click','view','error','purchase','login'])[1 + floor(random() * 5)::int],
         (ARRAY['north','south','east','west','central'])[1 + floor(random() * 5)::int],
         (ARRAY['amber','birch','cedar','delta','ember','fjord','grove','haven','iris','jade',
                'kiln','lark','mesa','nova','opal','pine','quartz','reed','slate','tide',
                'umber','vale','willow','xenon','yarrow','zephyr','aspen','brook','cliff','dune',
                'elm','frost','glen','hill','isle','jetty','knoll','lake','moor','nook'])[1 + floor(random() * 40)::int],
         jsonb_build_object('v', n %% 100),
         timestamp '2026-09-01' + (n::numeric / %s) * interval '30 days'
  FROM generate_series(%s, %s) AS n
$sql$, :rows, chunk_start, least(chunk_start + 999999, :rows)) AS statement
FROM generate_series(1, :rows, 1000000) AS chunk_start
\gexec

INSERT INTO lab_meta VALUES ('seed_max_id', (SELECT max(id) FROM events))
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
\endif
VACUUM (ANALYZE) events;

-- Recycle the seed's WAL into spare segments now, so the first big write later does not stall creating them.
CHECKPOINT;
```

- `\if :events_empty ... \endif` runs the block only for an empty table, so repeating `make db` does not double the data.
- `SELECT format($sql$ ... $sql$, :rows, chunk_start, least(chunk_start + 999999, :rows)) AS statement FROM generate_series(1, :rows, 1000000) AS chunk_start \gexec` is the trick that loads in chunks. `generate_series(1, :rows, 1000000)` produces 1, 1000001, 2000001, ... up to `rows`: the first id of each chunk. For each, `format(template, a, b, c)` fills the `%s` markers of the template (`%%` is a literal percent sign, as in `n %% 100`) and returns a ready-made `INSERT` statement as text. `$sql$ ... $sql$` is **dollar quoting**: a string literal that may contain quotes and newlines without escaping. `\gexec` is a psql command: it takes every cell of the result of the query just run and executes it as SQL. So a 2,000,000-row seed runs two inserts, and a 50,000,000-row seed runs fifty.
- Inside the template: `1 + floor(random() * 100000)::bigint` is a random device id from 1 to 100,000; `(ARRAY['click','view','error','purchase','login'])[1 + floor(random() * 5)::int]` picks an event type; the `region` and `city` expressions pick from five and forty names, **independently** of each other (this independence matters for the statistics step); `jsonb_build_object('v', n %% 100)` builds `{"v": n mod 100}`; `timestamp '2026-09-01' + (n::numeric / %s) * interval '30 days'` spreads the rows evenly over 30 days from 1 September 2026 (`n` divided by the total number of rows gives a fraction of the 30 days).
- `INSERT INTO lab_meta VALUES ('seed_max_id', (SELECT max(id) FROM events)) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;` records the highest id of the seed; `ON CONFLICT ... DO UPDATE` makes it an **upsert**: if the key exists, update it (`EXCLUDED` is the row that was refused).
- `VACUUM (ANALYZE) events;` and `CHECKPOINT;` (PostgreSQL note).

### `003_queries.sql`: the inspection queries

`sql/003_queries.sql`, lines 1 to 36:

```sql
-- 003_queries.sql: the inspection queries the lesson uses, with the lab's table in its baseline state.
SET timezone = 'UTC';

-- Step 1: how big is the table, and are its statistics fresh?
SELECT relname, n_live_tup, pg_size_pretty(pg_table_size('events')) AS table_size,
       pg_size_pretty(pg_indexes_size('events')) AS indexes_size, last_analyze
FROM pg_stat_user_tables WHERE relname = 'events';

-- Step 2: who is waiting for whom? (empty when nothing is blocked)
SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event_type, wait_event, left(query, 60) AS query
FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock';

-- Step 2: the lock queue on the table: granted locks first, then the waiting request.
SELECT pid, mode, granted FROM pg_locks WHERE relation = 'events'::regclass AND locktype = 'relation' ORDER BY granted DESC, pid;

-- Step 4: invalid indexes, the leftovers of an interrupted CREATE INDEX CONCURRENTLY (empty is good).
SELECT indexrelid::regclass AS invalid_index FROM pg_index WHERE NOT indisvalid;

-- Step 4: progress of a running index build (empty when none is running).
SELECT pid, phase, blocks_done, blocks_total, tuples_done, tuples_total FROM pg_stat_progress_create_index;

-- Step 5: the constraints on events and whether each is validated.
SELECT conname, convalidated, pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid = 'events'::regclass;

-- Step 3: bloat after a backfill: dead row versions and size (VACUUM reclaims space for reuse, not for the OS).
SELECT n_live_tup, n_dead_tup, pg_size_pretty(pg_table_size('events')) AS table_size FROM pg_stat_user_tables WHERE relname = 'events';

-- Step 6: what the planner knows about region and city (per column, then extended).
SELECT attname, n_distinct, null_frac FROM pg_stats WHERE tablename = 'events' AND attname IN ('region', 'city');
SELECT statistics_name, kinds, n_distinct IS NOT NULL AS has_ndistinct FROM pg_stats_ext WHERE tablename = 'events';

-- Step 6: the query whose plan flips. Region and city together; newest 100 rows (plan in explain/).
SELECT id, created_at FROM events WHERE region = 'pacific' AND city = 'seattle' ORDER BY created_at DESC LIMIT 100;

-- Step 6: how many rows the planner would need to be right about (0 until the new month is loaded).
SELECT count(*) AS pacific_seattle_rows FROM events WHERE region = 'pacific' AND city = 'seattle';
```

Step by step: table size and statistics freshness from `pg_stat_user_tables` (`pg_table_size`, `pg_indexes_size` and `pg_size_pretty` give sizes in readable units); who waits for whom (`pg_stat_activity` with `pg_blocking_pids(pid)`; `left(query, 60)` keeps the first 60 characters); the lock queue (`pg_locks`, with `'events'::regclass` converting the table name to its internal id); invalid indexes (`pg_index WHERE NOT indisvalid`); the progress of an index build; constraints and whether each is validated (`convalidated`, `pg_get_constraintdef`); bloat; the statistics of `region` and `city`; the query whose plan flips; and a count.

### Migrations

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
`sql/migrations/down/006_flagged_set_not_null.down.sql`, lines 1 to 13:

```sql
-- Undo migration 006: allow NULL again and put the (not yet validated) CHECK back, which is enforced for new
-- writes, so the state matches the end of move 1. Safe to run twice.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events ALTER COLUMN flagged DROP NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'flagged_not_null' AND conrelid = 'events'::regclass) THEN
    ALTER TABLE events ADD CONSTRAINT flagged_not_null CHECK (flagged IS NOT NULL) NOT VALID;
  END IF;
END
$$;
COMMIT;
```

The migration files (locks note, online schema changes note) use `BEGIN ... COMMIT` with `SET LOCAL lock_timeout`, `IF [NOT] EXISTS`, and a `DO $$ ... $$` block for statements that have no `IF NOT EXISTS`. A `DO` block runs procedural code once: `IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE ...) THEN ALTER TABLE ...; END IF;`. The down script of `006` shows both: it drops NOT NULL and re-creates the check only if it is not there.

### Naive statements and the reset

`sql/naive/03_set_not_null_scanning_the_table.sql`, lines 1 to 5:

```sql
-- The naive NOT NULL of step 5, on a scratch column: SET NOT NULL with no validated CHECK scans every row
-- while holding ACCESS EXCLUSIVE, so every query on events waits for the scan.
ALTER TABLE events ADD COLUMN IF NOT EXISTS scratch boolean DEFAULT false;
ALTER TABLE events ALTER COLUMN scratch SET NOT NULL;
ALTER TABLE events DROP COLUMN IF EXISTS scratch;
```
`sql/reset.sql`, lines 1 to 5:

```sql
-- reset.sql: drop everything the lab created, so 001 to 002 rebuild it from nothing. `make reset` runs this.
BEGIN;
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS lab_meta;
COMMIT;
```

The naive file adds a scratch column with a default, sets it `NOT NULL` (the scan under a strong lock) and drops it; the file runs the three statements in sequence. `reset.sql` drops both tables in one transaction (`CASCADE` also drops what depends on them).

## Try it yourself

(After `make up db`; `P="docker compose exec -T db psql -X -q -U lab -d lab"`.)

1. `$P -c "select region, count(*) from events group by region order by 1"` — five regions with about 400,000 rows each (seed) plus the rows the load added.
2. `$P -c "select event_type, count(*) from events group by event_type order by 2 desc"` — five event types, about 400,000 each.
3. `$P -c "select (array['a','b','c'])[2], 7 % 4, 7::numeric / 4, format('%s-%s', 1, 'x'), jsonb_build_object('v', 7)"` — prints `b`, `3`, `1.7500000000000000`, `1-x`, `{"v": 7}`.
4. `$P -c "select generate_series(1, 10, 4)"` — `1`, `5`, `9`: the chunk starts for a 10-row, 4-per-chunk load.
5. `$P < sql/003_queries.sql` — runs all the inspection queries.

## Mistakes people make

- `SELECT *` in application queries.
- Comparing with `= NULL`.
- Forgetting `WHERE` on `UPDATE` and `DELETE`.
- Wrapping an indexed column in a function in `WHERE`.
- Assuming rows come back in a fixed order without `ORDER BY`.
- Running a script twice and getting "already exists" errors (use `IF NOT EXISTS`).
- Time zone surprises with `timestamp` versus `timestamptz`.

**How this repository avoids them.** Every DDL has `IF [NOT] EXISTS`. The seed refuses to double-load and loads in chunks. Migrations are idempotent and have down scripts. Time zone is fixed. Statements with strong locks carry a `lock_timeout`.

## Check yourself

1. What do `WHERE` and `GROUP BY` each do? *`WHERE` filters rows; `GROUP BY` forms groups for aggregate functions.*
2. What does `IF NOT EXISTS` give a script? *Safe repetition: nothing happens, and no error, if the object exists.*
3. What does `x::int` do? *Converts the value `x` to the type integer.*
4. What happens to the statements between `BEGIN` and `ROLLBACK`? *Their effects are discarded.*
5. Why is `col = NULL` never true? *NULL means unknown, and comparing with unknown yields unknown; use `IS NULL`.*

## Further reading

- PostgreSQL 18, "SQL Commands": https://www.postgresql.org/docs/18/sql-commands.html and "The SQL Language": https://www.postgresql.org/docs/18/sql.html
- "Functions and Operators": https://www.postgresql.org/docs/18/functions.html

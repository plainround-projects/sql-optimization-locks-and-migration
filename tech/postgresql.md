# PostgreSQL

## What it is

**PostgreSQL** (often "Postgres") is a **database server**: a program that stores tables of data on disk and answers questions about them, written in a language called SQL. Many programs can connect to it at the same time over the network, and it keeps their changes consistent. It is free and open source. This repository uses major version **18**, run from the Docker image `postgres:18`.

## Why this repository uses it

The lesson is about what a real database does when its table is changed under load, so it needs a real one: real locks, real write-ahead log, a real planner. PostgreSQL 18 is the engine the track assumes. Every claim of the README is PostgreSQL's own output: lock views, plans, lock modes, table sizes.

## Where it appears

| File | What it does with PostgreSQL |
|---|---|
| `docker-compose.yml` | Starts `postgres:18` with lock logging and checkpoint settings. |
| `sql/001_schema.sql`, `002_seed.sql`, `003_queries.sql`, `reset.sql` | Create, fill, inspect and drop the lab's tables. |
| `sql/migrations/`, `sql/naive/`, `sql/experiments/` | The changes, the naive statements and the plan-flip load. |
| `sql/explain/*.sql` and `*.txt` | The plans and the captured lock queue. |
| `src/locks_lab/infrastructure/` | The Python side: load, locks, migrations, plan flip. |

## How it works underneath

**Server and processes.** One main process, the **postmaster**, listens on a network port (5432 by default). For every client connection it starts a separate **backend process**. Other background processes write dirty data to disk, write the log, and clean up (see below).

**Objects.** A server holds several **databases**; a database holds **schemas** (folders for names; `public` by default); a schema holds **tables**, **indexes**, **sequences**, **views** (saved queries) and **functions**. A **table** has **columns** (name and type) and **rows**. Common types: `integer`/`bigint` (whole numbers), `text`, `numeric(10,2)` (exact decimals), `timestamptz` (a moment in time with time zone), `boolean`. A **sequence** hands out increasing numbers; `BIGSERIAL` is a `bigint` column fed by a sequence. A **primary key** is a column (or set) whose values are unique; PostgreSQL builds an index for it automatically.

**Pages and the heap.** Table data lives in files on disk cut into **pages** of 8 kilobytes. A page holds several rows (**tuples**). The table's own file of pages, in no particular order, is called the **heap**. Reading a row means reading its page. A page read from disk is expensive; a page already in memory is cheap. PostgreSQL keeps recently used pages in **shared buffers** (a memory cache, set here to 512 MB), and the operating system keeps its own cache as well. A plan's `Buffers: shared hit=N read=M` counts pages found in the cache (`hit`) and pages fetched from outside it (`read`). **Pages touched** (hit + read) is a stable measure of work, while milliseconds depend on the machine.

**Transactions and MVCC.** A **transaction** is a group of statements that happen all together or not at all (`BEGIN ... COMMIT`, or `ROLLBACK` to undo). PostgreSQL uses **multi-version concurrency control (MVCC)**: an `UPDATE` or `DELETE` does not overwrite a row, it writes a new version and marks the old one as dead for later transactions. Readers never block writers. The price: dead row versions pile up.

**VACUUM.** `VACUUM` removes dead row versions so the space can be reused, and updates the **visibility map**, a small bitmap that records which pages hold only rows visible to everyone. `autovacuum` is a background process that does this automatically. `VACUUM (ANALYZE)` also refreshes statistics.

**WAL (write-ahead log).** Before any change reaches the table files, PostgreSQL writes a description of it to the **write-ahead log**. After a crash the server replays the log. Every inserted row writes a WAL record for the heap *and one for every index*, which is why indexes make writes more expensive.

**The planner and statistics.** For each statement the **planner** considers several ways to get the answer and picks the one with the lowest *estimated cost*, using **statistics** that `ANALYZE` collected: the number of rows, the most common values of each column, how many distinct values there are, and how closely the order of the values matches the order of the rows on disk (all visible in the `pg_stats` view). Wrong statistics lead to bad plans. `EXPLAIN` shows the chosen plan (see the EXPLAIN note).

**TOAST.** A row must fit in a page. A big value (more than about 2 kilobytes) is moved to a separate **TOAST table** ("The Oversized-Attribute Storage Technique") and the row keeps a pointer to it; it is also compressed unless told otherwise. Queries that do not select that column never touch the TOAST table. `ALTER TABLE ... ALTER COLUMN ... SET STORAGE EXTERNAL` stores the value out of line without compression.

**Catalogs and statistics views.** PostgreSQL describes itself in tables and views you can query: `pg_stat_user_tables` (rows, last analyze), `pg_stat_user_indexes` (how often each index was used), `pg_stats` (column statistics), `pg_class` (sizes in pages), `pg_locks`, `pg_stat_activity`. `pg_relation_size(oid)` gives bytes; `pg_size_pretty(n)` formats them.

**Settings.** Server settings (`shared_buffers`, `max_parallel_workers_per_gather`...) are set at start with `postgres -c name=value`, in a config file, or per session with `SET name = value`. `SHOW name` reads one.

## Walkthrough of this repository's use

### The server and its settings

`docker-compose.yml`, lines 13 to 29:

```yaml
    command:
      - postgres
      - -c
      - max_parallel_workers_per_gather=0
      - -c
      - shared_buffers=512MB
      - -c
      - log_lock_waits=on
      - -c
      - deadlock_timeout=1s
      - -c
      - max_wal_size=8GB
      - -c
      - min_wal_size=2GB
      - -c
      - checkpoint_timeout=15min
    shm_size: 768mb
```

(The Compose note explains each setting.) The ones that PostgreSQL concepts explain:

- **Write-ahead log and checkpoints.** Every change is first described in the WAL, a sequence of files; periodically a **checkpoint** writes all changed pages to the table files and lets old WAL be recycled. `max_wal_size=8GB` and `checkpoint_timeout=15min` make checkpoints rare, `min_wal_size=2GB` keeps WAL files around for reuse. A checkpoint writes a lot to disk at once, and the commits of the load wait behind that I/O, so one starting during a measurement would be blamed on the migration. `sql/002_seed.sql` ends with `CHECKPOINT;` for the same reason (below).
- **Lock logging.** `log_lock_waits=on` with `deadlock_timeout=1s` writes a line in the server log whenever a session waits more than one second for a lock.

### The table

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

`events` has 2,000,000 rows by default (the lesson uses 50,000,000). `id BIGSERIAL PRIMARY KEY`; `device_id BIGINT`; `event_type`, `region`, `city` as `TEXT`; `payload JSONB` (JSON stored in a binary form PostgreSQL can query and update; the load appends `{"seen": true}` with `payload || '{"seen": true}'`); `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` (`now()` is the time the transaction started; each row inserted by the load gets its own timestamp). `idx_events_created_at` exists from the start because the load's reads (`WHERE created_at >= now() - interval '1 minute'`) need it: the comment says the lesson's own index, `(device_id, created_at DESC)`, is a migration. `lab_meta` is a tiny table that remembers where the seed ended (`seed_max_id`), so the reset can delete everything the load and the experiments added.

### MVCC, dead rows and VACUUM

The load updates rows (`UPDATE events SET payload = ...`) and the backfill updates every old row once. In PostgreSQL an `UPDATE` writes a new row version and leaves the old one as a **dead tuple** until `VACUUM` removes it. `sql/003_queries.sql` has the bloat query:

`sql/003_queries.sql`, lines 25 to 26:

```sql
-- Step 3: bloat after a backfill: dead row versions and size (VACUUM reclaims space for reuse, not for the OS).
SELECT n_live_tup, n_dead_tup, pg_size_pretty(pg_table_size('events')) AS table_size FROM pg_stat_user_tables WHERE relname = 'events';
```

`n_live_tup`, `n_dead_tup` (dead row versions) and `pg_size_pretty(pg_table_size('events'))`. The report shows 117,714 dead versions after the backfill, with the comment "VACUUM reclaims space for reuse, not for the OS". `PostgresLabTable.reset()` ends with `VACUUM (ANALYZE) events` for this reason.

### The seed, in chunks

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

Described in the SQL note (`format`, `\gexec`, `generate_series`). The PostgreSQL parts: the whole load is a series of `INSERT ... SELECT` statements of one million rows each so that a 50-million-row load does not need one giant transaction; `VACUUM (ANALYZE) events` collects statistics and the visibility map; `CHECKPOINT;` forces a checkpoint right away, "to recycle the seed's WAL into spare segments now, so the first big write later does not stall creating them".

### JSONB

`payload JSONB` is a typed JSON column. `jsonb_build_object('v', n % 100)` builds `{"v": 42}` in the seed; `payload || '{"seen": true}'` merges two JSONB objects. The lab uses it because an update of a JSONB column rewrites the row, which is what the load needs: a realistic update workload.

### Statistics and activity views

The lab reads `pg_stat_user_tables` (size, live and dead rows, last analyze), `pg_stats` and `pg_stats_ext` (statistics note), `pg_stat_activity`, `pg_locks` and `pg_blocking_pids` (locks note), `pg_stat_progress_create_index` (progress of an index build: `phase`, `blocks_done`...), `pg_index` (index flags), `pg_constraint` (constraints and whether each is validated), `pg_class` (`relfilenode`, the table's file) and `pg_attribute` (`attnotnull`).

## Try it yourself

(After `make up db`.)

1. `docker compose exec db psql -U lab -d lab -c "show max_wal_size" -c "show checkpoint_timeout" -c "show log_lock_waits" -c "show deadlock_timeout"` — prints `8GB`, `15min`, `on`, `1s`.
2. `docker compose exec db psql -U lab -d lab -c "select relname, n_live_tup, n_dead_tup, pg_size_pretty(pg_table_size('events')) from pg_stat_user_tables where relname = 'events'"` — about 2,000,000 live rows and the table size (several hundred MB).
3. `docker compose exec db psql -U lab -d lab -c "select id, device_id, event_type, region, city, payload from events limit 3"` — three rows with `payload` like `{"v": 17}`.
4. `docker compose exec db psql -U lab -d lab -c "select payload || '{\"seen\": true}'::jsonb from events limit 1"` — a merged JSON object such as `{"v": 17, "seen": true}`.
5. `docker compose exec db psql -U lab -d lab -c "select * from lab_meta"` — the row `seed_max_id` with the highest id of the seed.
6. After `make load SECONDS=20`: `docker compose logs db | tail` — checkpoint messages if any; after `make run` look for `still waiting for AccessExclusiveLock` lines produced by `log_lock_waits`.

## Mistakes people make

- Assuming an index is always used (the planner may prefer a table scan, rightly or not).
- Judging a query by one timing without noticing that the cache was cold or warm.
- Forgetting `ANALYZE` after loading lots of data, so the planner works with stale statistics.
- Leaving transactions open, which stops `VACUUM` from cleaning.
- Using `SELECT *` on tables with big columns.
- Running a destructive command on the wrong database.

**How this repository avoids them.** Checkpoints are spaced out and forced before the measurement; dead rows are accounted for and vacuumed; the seed is chunked; the lab resets to a known row count; and everything the lab adds can be removed.

## Check yourself

1. What is a page, and how big is it? *The unit in which PostgreSQL stores and reads table data: 8 kilobytes holding several rows.*
2. What does MVCC do on `UPDATE`? *It writes a new version of the row and marks the old one dead; readers keep seeing the version that fits their snapshot.*
3. What does `VACUUM` do? *Removes dead row versions so space is reused and updates the visibility map.*
4. Why do indexes make inserts slower? *Each insert must also add an entry to every index, and each of those writes a WAL record.*
5. What is TOAST? *Out-of-line storage of large values in a separate table, so ordinary rows stay small.*

## Further reading

- PostgreSQL 18 documentation: https://www.postgresql.org/docs/18/ — "Database Physical Storage" (https://www.postgresql.org/docs/18/storage.html), "Concurrency Control" (https://www.postgresql.org/docs/18/mvcc.html), "Routine Vacuuming" (https://www.postgresql.org/docs/18/routine-vacuuming.html), "Write-Ahead Logging" (https://www.postgresql.org/docs/18/wal-intro.html), "Planner statistics" (https://www.postgresql.org/docs/18/planner-stats.html).

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

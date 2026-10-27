-- Step 6 before: the new month is loaded but statistics have not caught up. The planner has never seen 'pacific' or 'seattle' and expects one row.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, created_at FROM events WHERE region = 'pacific' AND city = 'seattle' ORDER BY created_at DESC LIMIT 100;

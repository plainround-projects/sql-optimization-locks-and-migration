-- Step 6 after CREATE STATISTICS (dependencies, mcv) on (region, city) and ANALYZE: the planner knows the pair, and the estimate matches.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, created_at FROM events WHERE region = 'pacific' AND city = 'seattle' ORDER BY created_at DESC LIMIT 100;

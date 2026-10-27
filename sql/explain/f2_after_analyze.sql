-- Step 6 after ANALYZE: per-column statistics know both values, but still multiply the two selectivities as if region and city were independent.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, created_at FROM events WHERE region = 'pacific' AND city = 'seattle' ORDER BY created_at DESC LIMIT 100;

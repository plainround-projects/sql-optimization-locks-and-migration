-- Step 4: build the lesson's index without blocking writes. Two table scans, cannot run in a transaction,
-- and an interrupted build leaves an INVALID index that must be dropped (see 003_queries.sql): IF NOT EXISTS
-- would skip over that leftover, so the application drops invalid indexes before it runs this file.
-- Undo: down/003_index_device_created_concurrently.down.sql.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_events_device_created ON events (device_id, created_at DESC);

-- Step 4: build the lesson's index without blocking writes. Two table scans, cannot run in a transaction,
-- and an interrupted build leaves an INVALID index that must be dropped (see 003_queries.sql).
CREATE INDEX CONCURRENTLY idx_events_device_created ON events (device_id, created_at DESC);

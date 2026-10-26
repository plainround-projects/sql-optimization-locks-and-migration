-- The naive index build of step 4: a plain CREATE INDEX holds a SHARE lock for the whole build, so inserts,
-- updates and deletes on events wait until it finishes. Reads still run.
CREATE INDEX idx_events_naive ON events (device_id, created_at DESC);

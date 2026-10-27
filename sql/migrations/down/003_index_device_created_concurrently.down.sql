-- Undo migration 003 without blocking writes. Cannot run in a transaction. Safe to run twice.
DROP INDEX CONCURRENTLY IF EXISTS idx_events_device_created;

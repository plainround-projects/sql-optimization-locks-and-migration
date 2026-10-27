-- Undo migration 001. Dropping a column is metadata-only; the lock_timeout keeps it out of the lock queue.
-- Safe to run twice.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events DROP COLUMN IF EXISTS flagged;
COMMIT;

-- Undo migration 004. Safe to run twice.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events DROP CONSTRAINT IF EXISTS flagged_not_null;
COMMIT;

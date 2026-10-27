-- Step 5, move 3: ACCESS EXCLUSIVE for a moment. PostgreSQL sees the validated CHECK and skips the scan.
-- Contract: the CHECK is now redundant with the column's NOT NULL, so drop it.
-- Safe to run twice. Undo: down/006_flagged_set_not_null.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events ALTER COLUMN flagged SET NOT NULL;
ALTER TABLE events DROP CONSTRAINT IF EXISTS flagged_not_null;
COMMIT;

-- Step 5, move 3: ACCESS EXCLUSIVE for a moment. PostgreSQL sees the validated CHECK and skips the scan.
-- Contract: the CHECK is now redundant with the column's NOT NULL, so drop it.
SET lock_timeout = '2s';
BEGIN;
ALTER TABLE events ALTER COLUMN flagged SET NOT NULL;
ALTER TABLE events DROP CONSTRAINT flagged_not_null;
COMMIT;

-- Step 5, move 1: ACCESS EXCLUSIVE for a moment (metadata only). New writes are checked from now on;
-- existing rows are not looked at yet. ADD CONSTRAINT has no IF NOT EXISTS, so the DO block makes it repeatable.
-- Safe to run twice. Undo: down/004_flagged_check_not_valid.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'flagged_not_null' AND conrelid = 'events'::regclass) THEN
    ALTER TABLE events ADD CONSTRAINT flagged_not_null CHECK (flagged IS NOT NULL) NOT VALID;
  END IF;
END
$$;
COMMIT;

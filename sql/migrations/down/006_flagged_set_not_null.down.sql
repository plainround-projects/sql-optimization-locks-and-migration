-- Undo migration 006: allow NULL again and put the (not yet validated) CHECK back, which is enforced for new
-- writes, so the state matches the end of move 1. Safe to run twice.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events ALTER COLUMN flagged DROP NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'flagged_not_null' AND conrelid = 'events'::regclass) THEN
    ALTER TABLE events ADD CONSTRAINT flagged_not_null CHECK (flagged IS NOT NULL) NOT VALID;
  END IF;
END
$$;
COMMIT;

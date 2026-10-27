-- Step 3, expand: a nullable column and a default for new rows. Both are metadata-only (no table rewrite),
-- and the lock_timeout makes the statement give up instead of queueing behind a long transaction.
-- Safe to run twice. Undo: down/001_add_flagged_column.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events ADD COLUMN IF NOT EXISTS flagged boolean;
ALTER TABLE events ALTER COLUMN flagged SET DEFAULT false;
COMMIT;

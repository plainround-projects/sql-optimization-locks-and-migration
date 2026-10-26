-- Step 3, expand: a nullable column and a default for new rows. Both are metadata-only (no table rewrite),
-- and the lock_timeout makes the statement give up instead of queueing behind a long transaction.
SET lock_timeout = '2s';
BEGIN;
ALTER TABLE events ADD COLUMN flagged boolean;
ALTER TABLE events ALTER COLUMN flagged SET DEFAULT false;
COMMIT;

-- Step 5, move 1: ACCESS EXCLUSIVE for a moment (metadata only). New writes are checked from now on;
-- existing rows are not looked at yet.
SET lock_timeout = '2s';
ALTER TABLE events ADD CONSTRAINT flagged_not_null CHECK (flagged IS NOT NULL) NOT VALID;

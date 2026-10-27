-- Step 5, move 2: the real scan, under SHARE UPDATE EXCLUSIVE, which allows reads, inserts, updates and deletes.
-- Validating an already validated constraint does nothing, so this is safe to run twice.
-- Undo: there is nothing to undo; down/005_validate_flagged_check.down.sql says so.
ALTER TABLE events VALIDATE CONSTRAINT flagged_not_null;

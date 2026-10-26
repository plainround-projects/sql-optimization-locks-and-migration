-- Step 5, move 2: the real scan, under SHARE UPDATE EXCLUSIVE, which allows reads, inserts, updates and deletes.
ALTER TABLE events VALIDATE CONSTRAINT flagged_not_null;

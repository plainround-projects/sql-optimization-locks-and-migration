-- The naive NOT NULL of step 5, on a scratch column: SET NOT NULL with no validated CHECK scans every row
-- while holding ACCESS EXCLUSIVE, so every query on events waits for the scan.
ALTER TABLE events ADD COLUMN IF NOT EXISTS scratch boolean DEFAULT false;
ALTER TABLE events ALTER COLUMN scratch SET NOT NULL;
ALTER TABLE events DROP COLUMN IF EXISTS scratch;

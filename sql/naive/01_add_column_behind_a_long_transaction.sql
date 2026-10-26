-- The naive migration of step 2: no lock_timeout. Run it in session B while session A holds
-- `BEGIN; SELECT * FROM events WHERE id = 1;` open. The ALTER waits for A, and everything after it waits for the ALTER.
ALTER TABLE events ADD COLUMN flagged boolean;

-- Step 3, backfill: one batch. app/migrate.py runs it for id ranges of 10,000 with a pause between batches.
-- The value is derived from existing data, which is why a backfill is needed at all (a constant default
-- would need none in PostgreSQL 11 and later). Run by hand: psql -v first_id=1 -v last_id=10000 < this file.
SET lock_timeout = '2s';
UPDATE events SET flagged = (event_type = 'error')
WHERE id BETWEEN :first_id AND :last_id AND flagged IS NULL;

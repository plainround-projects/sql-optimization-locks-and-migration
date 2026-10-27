-- Step 3, backfill: one batch. The application runs it for id ranges with a pause between batches.
-- The value is derived from existing data, which is why a backfill is needed at all (a constant default
-- would need none in PostgreSQL 11 and later). Only rows still NULL are touched, so a batch can be repeated.
-- Run by hand: psql -v first_id=1 -v last_id=2000 < this file. Undo: down/002_backfill_flagged_batch.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
UPDATE events SET flagged = (event_type = 'error')
WHERE id BETWEEN :first_id AND :last_id AND flagged IS NULL;
COMMIT;

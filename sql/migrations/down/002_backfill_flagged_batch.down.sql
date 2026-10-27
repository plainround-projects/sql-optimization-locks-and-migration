-- Undo one backfill batch: put NULL back. Run by hand: psql -v first_id=1 -v last_id=2000 < this file.
-- Safe to run twice.
BEGIN;
SET LOCAL lock_timeout = '2s';
UPDATE events SET flagged = NULL WHERE id BETWEEN :first_id AND :last_id AND flagged IS NOT NULL;
COMMIT;

-- reset.sql: drop everything the lab created, so 001 to 002 rebuild it from nothing. `make reset` runs this.
BEGIN;
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS lab_meta;
COMMIT;

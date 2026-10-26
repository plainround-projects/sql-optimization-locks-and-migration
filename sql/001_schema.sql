-- 001_schema.sql: DDL for the "Locks and migration" lab (PostgreSQL 18).
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS lab_meta;

CREATE TABLE events (
  id         BIGSERIAL   PRIMARY KEY,
  device_id  BIGINT      NOT NULL,
  event_type TEXT        NOT NULL,
  region     TEXT        NOT NULL,
  city       TEXT        NOT NULL,
  payload    JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  events            IS 'The busy table: inserts, updates and reads never stop while the lab changes it.';
COMMENT ON COLUMN events.region     IS 'Seeded independently of city; the plan-flip experiment loads a month where the two are correlated.';
COMMENT ON COLUMN events.created_at IS 'Seed rows are September 2026; the load script adds rows stamped now().';

-- The load script reads "recent events" with a predicate on created_at, so the table starts with this index.
-- The lesson's index (device_id, created_at DESC) is a migration, not part of the baseline.
CREATE INDEX idx_events_created_at ON events (created_at);

-- Where the seed ended, so the lab can delete everything the load and the experiments added.
CREATE TABLE lab_meta (key TEXT PRIMARY KEY, value BIGINT NOT NULL);

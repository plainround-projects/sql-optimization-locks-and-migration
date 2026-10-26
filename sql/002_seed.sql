-- 002_seed.sql: DML. :rows events (default 2,000,000), analyzed, with region and city independent.
-- Run as: psql -v rows=50000000 < sql/002_seed.sql   (the lesson's size)
\if :{?rows}
\else
  \set rows 2000000
\endif
SELECT setseed(0.42);
SET timezone = 'UTC';

-- Loaded in chunks of 1,000,000 so a 50,000,000-row load does not need one huge transaction.
SELECT format($sql$
  INSERT INTO events (device_id, event_type, region, city, payload, created_at)
  SELECT 1 + floor(random() * 100000)::bigint,
         (ARRAY['click','view','error','purchase','login'])[1 + floor(random() * 5)::int],
         (ARRAY['north','south','east','west','central'])[1 + floor(random() * 5)::int],
         (ARRAY['amber','birch','cedar','delta','ember','fjord','grove','haven','iris','jade',
                'kiln','lark','mesa','nova','opal','pine','quartz','reed','slate','tide',
                'umber','vale','willow','xenon','yarrow','zephyr','aspen','brook','cliff','dune',
                'elm','frost','glen','hill','isle','jetty','knoll','lake','moor','nook'])[1 + floor(random() * 40)::int],
         jsonb_build_object('v', n %% 100),
         timestamp '2026-09-01' + (n::numeric / %s) * interval '30 days'
  FROM generate_series(%s, %s) AS n
$sql$, :rows, chunk_start, least(chunk_start + 999999, :rows)) AS statement
FROM generate_series(1, :rows, 1000000) AS chunk_start
\gexec

INSERT INTO lab_meta VALUES ('seed_max_id', (SELECT max(id) FROM events));
VACUUM (ANALYZE) events;

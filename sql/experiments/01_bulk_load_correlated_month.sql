-- Step 6: a new market launches. One month of rows (October 2026) where region and city are correlated:
-- every row is region 'pacific' and its city is one of four pacific cities. 'pacific' and 'seattle' did not
-- exist when the table was last analyzed, so the planner has never seen them.
-- Autovacuum is switched off for the table during the experiment so its analyze does not run mid-way;
-- production has it on, and 10% of a big table is a lot of rows to load before it wakes up.
ALTER TABLE events SET (autovacuum_enabled = false);

INSERT INTO events (device_id, event_type, region, city, payload, created_at)
SELECT 1 + floor(random() * 100000)::bigint,
       (ARRAY['click','view','error','purchase','login'])[1 + floor(random() * 5)::int],
       'pacific',
       (ARRAY['seattle','portland','tacoma','spokane'])[1 + (n % 4)],
       jsonb_build_object('v', n % 100),
       timestamp '2026-10-01' + (n::numeric / 600000) * interval '30 days'
FROM generate_series(1, 600000) AS n
WHERE NOT EXISTS (SELECT 1 FROM events WHERE region = 'pacific');   -- repeatable: loads the month once

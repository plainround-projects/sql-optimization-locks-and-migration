# PostgreSQL planner statistics

## What it is

Before running a query, PostgreSQL's **planner** has to guess how many rows each step will produce, because the best plan depends on it: an index lookup is best for 100 rows, a full scan for 100 million. It guesses from **statistics** it has gathered about the data. When the statistics are old or missing, the guess is wrong and the plan can be terrible, though the query and the data have not changed in any way you can see. That is a **plan regression** (or plan flip).

## Why this repository uses it

Step 6 of the lesson is a plan regression you cause yourself: a new market launches, a month of rows is bulk-loaded with a region and city the planner has never seen, and a query that took 0.1 ms starts taking 758 ms. The fix is two statistics commands. The experiment shows the three plans side by side with the estimates.

## Where it appears

| File | Role |
|---|---|
| `sql/experiments/01_bulk_load_correlated_month.sql` | The bulk load (600,000 rows, `region = 'pacific'`, four cities). |
| `sql/explain/f1_stale_statistics.sql` / `.txt` | The query planned with stale statistics. |
| `sql/explain/f2_after_analyze.sql` / `.txt` | After `ANALYZE`. |
| `sql/explain/f3_after_extended_statistics.sql` / `.txt` | After `CREATE STATISTICS` and `ANALYZE`. |
| `src/locks_lab/infrastructure/plan_flip.py` | Runs the three steps. |
| `src/locks_lab/domain/flip.py` | Reads the estimates and nodes from a plan. |
| `sql/003_queries.sql` | Inspects `pg_stats` and `pg_stats_ext`. |
| `docker-compose.yml` | Autovacuum stays on (comment on line 2). |
| `tests/integration/test_lesson_outcomes.py` | `test_step6_...` asserts the story. |

## How it works underneath

**`ANALYZE`** reads a random sample of the table (30,000 rows with the default settings: 300 times the "statistics target" of 100) and stores, per column, in the catalog `pg_statistic` (readable as the view **`pg_stats`**): `null_frac` (the fraction of NULLs), `n_distinct` (how many different values), `most_common_vals` with `most_common_freqs`, and a histogram for the other values. `VACUUM (ANALYZE)` does both jobs.

**Selectivity and independence.** For `WHERE region = 'pacific' AND city = 'seattle'` the planner estimates the fraction of rows for each condition and **multiplies** them, assuming the two columns are *independent*. If every Seattle row is also a Pacific row, the true fraction is far bigger than the product, and the estimate is far too small. A value the planner has never seen (not in the most-common list, and no row sampled) gets a tiny default estimate, often one row.

**Autovacuum and autoanalyze.** A background process analyzes a table automatically when the number of rows changed since the last analyze exceeds `autovacuum_analyze_threshold + autovacuum_analyze_scale_factor × rows` (defaults 50 and 0.1, so about 10% of the table). After a bulk load smaller than that, or before the process wakes up, the statistics are stale. `ALTER TABLE t SET (autovacuum_enabled = false)` switches it off for one table; `ALTER TABLE t RESET (autovacuum_enabled)` restores the default.

**Extended statistics.** `CREATE STATISTICS name (kinds) ON col1, col2 FROM table;` tells `ANALYZE` to gather statistics across several columns, visible in `pg_stats_ext`. Kinds: `dependencies` (functional dependencies: "knowing `city` determines `region`"), `ndistinct` (distinct combinations) and `mcv` (the most common *combinations* of values with their frequencies). `mcv` is the most precise for combinations that appear often.

**Estimate versus actual.** `EXPLAIN (ANALYZE)` prints `rows=` (the estimate) next to `actual ... rows=`. A big gap is the symptom to look for. Fixes: `ANALYZE` after bulk loads, lower the autovacuum threshold for large tables, extended statistics for correlated columns, or rewrite the query so that the plan does not depend on the guess.

**Why the wrong plan can be so bad.** With an estimate of 1 row, the planner chooses "scan everything, sort, take 100", which is fine for one row but reads the whole table when 150,000 rows match. With the right estimate it chooses "walk the time index backwards and stop after 100 matches".

## Walkthrough of this repository's use

### The setup

`sql/experiments/01_bulk_load_correlated_month.sql`, lines 1 to 16:

```sql
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
```

The seed (`sql/002_seed.sql`) chose `region` (five values) and `city` (forty values) **independently** and never wrote `'pacific'`, `'seattle'`, `'portland'`, `'tacoma'` or `'spokane'`. This file loads October 2026: 600,000 rows, all `region = 'pacific'`, with the city one of four (`(ARRAY['seattle','portland','tacoma','spokane'])[1 + (n % 4)]`: `n % 4` is the remainder 0 to 3 and array positions start at 1), so a quarter of them, 150,000, are Seattle. The timestamps spread over the 30 days of October: `timestamp '2026-10-01' + (n::numeric / 600000) * interval '30 days'`. `ALTER TABLE events SET (autovacuum_enabled = false)` switches autovacuum off for this table during the experiment (the comment: production has it on, and 10% of a big table is a lot of rows to load before it wakes up). The last line `WHERE NOT EXISTS (SELECT 1 FROM events WHERE region = 'pacific')` makes the load repeatable: it runs once.

### The query and the three plans

`sql/explain/f1_stale_statistics.sql`, lines 1 to 4:

```sql
-- Step 6 before: the new month is loaded but statistics have not caught up. The planner has never seen 'pacific' or 'seattle' and expects one row.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, created_at FROM events WHERE region = 'pacific' AND city = 'seattle' ORDER BY created_at DESC LIMIT 100;
```

`SELECT id, created_at FROM events WHERE region = 'pacific' AND city = 'seattle' ORDER BY created_at DESC LIMIT 100`: "the newest 100 Seattle events". 

**Before statistics catch up** (`f1_stale_statistics.txt`): the planner has never seen these values, so it expects **one row** (`rows=1` on the `Seq Scan`) and chooses to read the whole table, sort, and take 100. In fact 150,000 rows match (`actual ... rows=150000.00`), `Rows Removed by Filter: 2460839`, and it takes 758 ms.

`sql/explain/f2_after_analyze.txt`, lines 1 to 8:

```text
Limit  (cost=0.43..936.66 rows=100 width=16) (actual time=0.021..0.105 rows=100.00 loops=1)
  Buffers: shared hit=10
  ->  Index Scan Backward using idx_events_created_at on events  (cost=0.43..322764.45 rows=34475 width=16) (actual time=0.019..0.095 rows=100.00 loops=1)
        Filter: ((region = 'pacific'::text) AND (city = 'seattle'::text))
        Rows Removed by Filter: 297
        Index Searches: 1
        Buffers: shared hit=10
Planning:
```

**After `ANALYZE events`** (`f2`): the planner now knows `pacific` and `seattle` exist, but estimates 34,475 rows (`rows=34475` on the `Index Scan Backward` line of `f2_after_analyze.txt`) by multiplying the two selectivities as if independent. It is wrong by a factor of four, but good enough: it now chooses to walk the index on `created_at` backwards (`Index Scan Backward using idx_events_created_at`) and filter, stopping after 100 matches: 0.13 ms.

`sql/explain/f3_after_extended_statistics.txt`, lines 1 to 6:

```text
Limit  (cost=0.43..209.19 rows=100 width=16) (actual time=0.014..0.068 rows=100.00 loops=1)
  Buffers: shared hit=10
  ->  Index Scan Backward using idx_events_created_at on events  (cost=0.43..323965.28 rows=155189 width=16) (actual time=0.013..0.060 rows=100.00 loops=1)
        Filter: ((region = 'pacific'::text) AND (city = 'seattle'::text))
        Rows Removed by Filter: 297
        Index Searches: 1
```

**After extended statistics** (`f3`): estimate 155,189, close to the real 150,000, same fast plan (0.108 ms). In `results.md` the three rows are: estimate 1 / 150,000 actual / `Sort / Seq Scan` / 758 ms; 34,475 / `Index Scan Backward` / 0.134 ms; 155,189 / `Index Scan Backward` / 0.108 ms.

The two commands (from the adapter):

`src/locks_lab/infrastructure/plan_flip.py`, lines 21 to 42:

```python
    def run(self) -> FlipOutcome:
        plans: dict[str, tuple[str, ...]] = {}
        with session(self._settings, application_name="plan-flip") as connection:
            run_file(connection, self._sql_dir / "experiments" / "01_bulk_load_correlated_month.sql")
            actual = int(
                scalar(connection, "SELECT count(*) FROM events WHERE region = 'pacific' AND city = 'seattle'")
            )

            def capture(name: str) -> None:
                rows = run_file(connection, self._sql_dir / "explain" / f"{name}.sql")
                plans[name] = tuple(row[0] for row in rows)

            first, second, third = FLIP_PLANS
            capture(first)
            connection.execute("ANALYZE events")
            capture(second)
            connection.execute(
                f"CREATE STATISTICS {EXTENDED_STATISTICS} (dependencies, mcv) ON region, city FROM events"
            )
            connection.execute("ANALYZE events")
            capture(third)
        return FlipOutcome(actual, plans)
```

`ANALYZE events` after the capture of `f1`; `CREATE STATISTICS events_region_city (dependencies, mcv) ON region, city FROM events` and another `ANALYZE events` before the capture of `f3`. The lesson names `dependencies`; this lab adds `mcv` because `dependencies` alone only lifted the estimate to about 60,000 against 150,000 (the architecture note records it), while `mcv` knows the exact frequency of each (region, city) pair.

### What the planner knows, in the catalog

`sql/003_queries.sql`, lines 28 to 36:

```sql
-- Step 6: what the planner knows about region and city (per column, then extended).
SELECT attname, n_distinct, null_frac FROM pg_stats WHERE tablename = 'events' AND attname IN ('region', 'city');
SELECT statistics_name, kinds, n_distinct IS NOT NULL AS has_ndistinct FROM pg_stats_ext WHERE tablename = 'events';

-- Step 6: the query whose plan flips. Region and city together; newest 100 rows (plan in explain/).
SELECT id, created_at FROM events WHERE region = 'pacific' AND city = 'seattle' ORDER BY created_at DESC LIMIT 100;

-- Step 6: how many rows the planner would need to be right about (0 until the new month is loaded).
SELECT count(*) AS pacific_seattle_rows FROM events WHERE region = 'pacific' AND city = 'seattle';
```

`pg_stats` shows, per column, `n_distinct` and `null_frac`; `pg_stats_ext` shows the extended statistic and its kinds (`kinds` is `{f,m}` after `CREATE STATISTICS ... (dependencies, mcv)`: `f` functional dependencies, `m` most common values). The last query counts the matching rows, 0 until the new month is loaded.

### The test

`tests/integration/test_lesson_outcomes.py`, lines 150 to 163:

```python
def test_step6_a_plan_flips_on_stale_statistics_and_is_fixed_by_extended_statistics(scenarios, connection):
    flip = scenarios.plan_flip()
    stale, analyzed, extended = (flip.plans[name] for name in sorted(flip.plans))
    assert flip.actual_rows == 150_000
    assert stale.estimate * 1000 < flip.actual_rows, "the planner expected one row"
    assert stale.scans_everything
    assert analyzed.estimate * 2 < flip.actual_rows, "ANALYZE still multiplies region by city as if independent"
    assert analyzed.walks_the_index
    assert abs(extended.estimate - flip.actual_rows) <= 0.1 * flip.actual_rows, "extended statistics know the pair"
    assert stale.milliseconds > 20 * extended.milliseconds
    kinds = connection.execute("SELECT kinds FROM pg_stats_ext WHERE statistics_name = 'events_region_city'").fetchone()
    assert kinds is not None
    assert sorted(kinds[0]) == ["f", "m"], "functional dependencies and mcv"
    assert parse_flip_plan(flip.lines["f3_after_extended_statistics"]).estimate == extended.estimate
```

`stale.estimate * 1000 < flip.actual_rows` (the planner expected about one row against 150,000); `stale.scans_everything`; `analyzed.estimate * 2 < flip.actual_rows` (still too low: independence); `analyzed.walks_the_index`; `abs(extended.estimate - flip.actual_rows) <= 0.1 * flip.actual_rows` (within 10%); the stale plan is more than 20 times slower than the extended one; and `pg_stats_ext.kinds` sorted is `["f", "m"]`.

### Preventing it

The README lists them: `ANALYZE` after bulk loads; lower the autovacuum analyze threshold for big tables (`ALTER TABLE events SET (autovacuum_analyze_scale_factor = 0.01)`); extended statistics for correlated columns; compare `rows=` with `actual rows=` in important plans; and prefer a query shape that does not depend on the estimate.

## Try it yourself

(After `make up db`; `P="docker compose exec -T db psql -X -q -U lab -d lab"`.)

1. `$P -c "select attname, n_distinct, null_frac from pg_stats where tablename='events' and attname in ('region','city')"` — `region` has 5 distinct values, `city` 40.
2. Load the new month: `$P < sql/experiments/01_bulk_load_correlated_month.sql`, then `$P < sql/explain/f1_stale_statistics.sql` — a plan with `Seq Scan` and `rows=1` on the scan, and an `Execution Time` of hundreds of milliseconds (it varies by machine).
3. `$P -c "analyze events"` then `$P < sql/explain/f2_after_analyze.sql` — `Index Scan Backward`, estimate in the tens of thousands.
4. `$P -c "create statistics events_region_city (dependencies, mcv) on region, city from events" -c "analyze events"` then `$P < sql/explain/f3_after_extended_statistics.sql` — estimate close to 150,000. `$P -c "select statistics_name, kinds from pg_stats_ext"` shows `events_region_city | {f,m}`: `f` is functional dependencies and `m` is most common values.
5. `make reset db` (or `make run`, which resets itself) puts everything back, including the autovacuum setting.

## Mistakes people make

- Assuming the planner knows data that was loaded a minute ago.
- Fixing a bad plan with hints or index tricks before checking the estimates.
- Creating extended statistics and forgetting to `ANALYZE` afterwards (they are only filled by an analyze).
- Trusting an average over time: plans can be fine for months and flip on a data change.

**How this repository avoids them.** The experiment resets itself (drops the statistics object, deletes the added rows, restores autovacuum). The prevention list is in the README and the plans of all three moments are committed. The test asserts the estimates, not just the times.

## Check yourself

1. What is the symptom of a statistics problem in a plan? *The estimated `rows=` is far from the actual rows.*
2. Why does the planner underestimate `region = 'a' AND city = 'b'` for correlated columns? *It multiplies the two selectivities as if the columns were independent.*
3. When does autovacuum analyze a table? *When the rows changed since the last analyze exceed the threshold plus the scale factor times the table size (about 10% by default).*
4. What does `CREATE STATISTICS ... (dependencies, mcv)` change? *`ANALYZE` also gathers statistics about the pair of columns, so combined conditions are estimated better.*
5. What must you run after `CREATE STATISTICS`? *`ANALYZE`, which fills them.*

## Further reading

- PostgreSQL 18, "Planner Statistics": https://www.postgresql.org/docs/18/planner-stats.html and "Multivariate statistics examples": https://www.postgresql.org/docs/18/multivariate-statistics-examples.html
- `CREATE STATISTICS`: https://www.postgresql.org/docs/18/sql-createstatistics.html ; `pg_stats`: https://www.postgresql.org/docs/18/view-pg-stats.html ; autovacuum: https://www.postgresql.org/docs/18/routine-vacuuming.html#AUTOVACUUM

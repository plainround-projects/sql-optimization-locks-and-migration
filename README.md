# SQL optimization: locks and migration

A busy PostgreSQL 18 table under constant read and write load from a script, and the three changes you must make to it while the load keeps running: add a column and backfill it, add an index, and make the column `NOT NULL`. You first do each the naive way and watch what blocks, then do it safely, then cause a plan regression with stale and missing statistics and fix it.

This repository is the runnable build of the Plainround lesson **"Change a huge busy table without blocking it"** (`/prep/sql-optimization/project-locks-and-migration`, planned at **14 hours**). It uses PostgreSQL, the engine the lesson names for the lock experiments.

## What is in it

| Piece | Where |
|---|---|
| PostgreSQL 18 in Docker | `docker-compose.yml` |
| Schema (DDL), seed (DML), the inspection queries the lesson uses | `sql/001_schema.sql`, `sql/002_seed.sql`, `sql/003_queries.sql` |
| The safe changes, one file per step | `sql/migrations/001` to `006` |
| The three naive statements, to run by hand | `sql/naive/` |
| The plan-flip data load | `sql/experiments/` |
| The plans of the flip (`.sql` to run, `.txt` captured), the lock queue snapshot, and the numbers | `sql/explain/` |
| The load script (steady inserts, updates and reads; p99 and errors every second) | `app/load.py` |
| The safe-migration tools: retry on `lock_timeout`, batched backfill, lock report, interrupted-build helper | `app/migrate.py` |
| Each experiment as a function, and the script that chains them | `app/scenarios.py`, `scripts/run_lesson.py` |
| Tests, one per "Done when" line | `tests/test_lesson.py` |
| How it fits together, and why | [ARCHITECTURE.md](ARCHITECTURE.md) |

## Prerequisites

| Tool | Version used | Notes |
|---|---|---|
| Docker with Compose v2 | Docker 24 or newer | Runs PostgreSQL. No local PostgreSQL or `psql` needed. |
| Python | 3.12 or newer | Runs the load, the migrations and the tests in a virtual environment (`.venv/`). |
| make | any | |
| PostgreSQL | **18** (`postgres:18`, tested on 18.6) | The track assumes PostgreSQL 18 as of October 2026. The lock modes and `NOT VALID` behavior used here are the same from PostgreSQL 12. |
| Python packages | psycopg 3, pytest | `make run` and `make test` install them. |

Free disk: about 2 GB at the default size (the table grows to about 360 MB during the backfill, plus WAL). Memory: 512 MB of shared buffers and 768 MB of shared memory in the container. Port 55433 (change it in `.env`, see `.env.example`).

## Setup, run, test, stop

```bash
make up      # start PostgreSQL 18 on localhost:55433 and wait until it is healthy
```

```bash
make db      # schema, then 2,000,000 events (about 10 seconds), then the lesson's inspection queries
```

```bash
make run     # replay the lesson with the load running throughout: about 5 minutes with a 60-second baseline
```

```bash
make test    # 9 tests, about 3 minutes, with the load script running during each
```

```bash
make down    # stop PostgreSQL and delete its volume
```

Settings (all optional, also in `.env.example`):

- `ROWS=50000000 make db` builds the lesson's 50,000,000-row table (about 12 GB on disk). The default is 2,000,000: every lock effect is the same, the stalls are shorter.
- `BASELINE_SECONDS=600 make run` uses the lesson's ten-minute baseline; the numbers committed under `sql/explain/` come from that run. The default is 60.
- `BACKFILL_BATCH=10000 make run` uses the lesson's backfill batch size; the default is 2,000 (see below). `make sweep` measures which size keeps p99 inside the bar, from a fresh database for each arm (it recreates the database and takes about seven minutes; the committed result is `sql/explain/backfill-sweep.txt`).
- `make load SECONDS=120` runs the load script alone and prints its one-second lines, which is the way to watch the table while you try the naive statements from `sql/naive/` in `make psql` sessions.

`make run` rewrites `sql/explain/results.md`, `lock_queue.txt` and the `f*.txt` plans. It also writes `load-metrics.jsonl` (ignored by git), one record per second with the step names marked in it.

## What the build does

| Step | What happens | Where to see it |
|---|---|---|
| 1 | The load runs for the baseline period: 40 iterations a second of insert, update of a recent row, and read of recent events (120 operations a second). | `results.md`, "baseline" rows |
| 2 | A session reads and stays open. A naive `ALTER TABLE ... ADD COLUMN` waits for it, and the load's inserts wait for the `ALTER`. | `lock_queue.txt`, step 2 of `results.md` |
| 3 | The safe version: `lock_timeout` with retry, the column without a rewrite, a batched backfill (2,000 rows at a time by default, the lesson starts at 10,000) with a pause. A forced conflict makes it fail fast. | `results.md`, `backfill-sweep.txt` |
| 4 | A plain `CREATE INDEX` stalls writes; `CREATE INDEX CONCURRENTLY` does not. A build cancelled on purpose leaves an invalid index that is found and dropped. | `results.md` |
| 5 | `NOT NULL` in three moves, each with the lock it held. | `results.md` |
| 6 | A correlated month is loaded; the query is planned before statistics catch up, after `ANALYZE`, and after extended statistics. | `f1_*.txt`, `f2_*.txt`, `f3_*.txt` |

## Done when: how each line is proved

The numbers below come from `sql/explain/results.md`, the last `make run` with `BASELINE_SECONDS=600`. They were measured on a laptop that other work was also using, so read the shapes; your milliseconds will differ.

| Window | p99 ms | Max ms | Errors | Stalled seconds |
|---|---:|---:|---:|---:|
| Baseline, opening (600 s, 120 operations a second) | 3.23 | 105 | 0 | 0 |
| Baseline, closing (20 s) | 5.72 | 60 | 0 | 0 |
| Naive `ALTER` behind a long read (6 s) | 3,010 | 3,010 | 5 | 6 |
| Safe migration: column and 1,013 backfill batches (79 s) | 16.2 | 194 | 0 | 0 |
| Plain `CREATE INDEX` (0.7 s build) | 604 | 609 | 0 | 0 |
| `CREATE INDEX CONCURRENTLY` (0.8 s build) | 44.9 | 45 | 0 | 0 |
| Naive `SET NOT NULL` (177 ms scan) | 157 | 158 | 0 | 0 |
| `NOT NULL` in three moves | 13.6 | 14 | 0 | 0 |

Locks held by the three moves: `ACCESS EXCLUSIVE` for 0.9 ms, `SHARE UPDATE EXCLUSIVE` for 138 ms (the validation scan, with reads and writes flowing), `ACCESS EXCLUSIVE` for 0.5 ms. The plan flip: estimate 1 row against 150,000 found (143 ms, `Seq Scan` and `Sort`); after `ANALYZE` an estimate of 35,615 and the index plan (0.06 ms); after extended statistics an estimate of 148,458. The backfill took the table from 194 MB to 400 MB with 252,434 dead row versions.

**What this run did not show.** The safe migration's p99 (16.2 ms) is 2.8 times the higher baseline (5.72 ms): in this run the "within twice baseline" line was not met. The same code met it in other runs (10.05 ms against 7.13 in an earlier ten-minute run, with 10,000-row batches), and failed it in others (17.8 ms against a bar of 8.0 in a test run). p99 of single-millisecond statements on a laptop shared with other work moves by a factor of two or three between runs, and the backfill's cost sits right at the bar. What the lab shows reliably is the order of magnitude: the naive changes stall the load for seconds (p99 around 3,000 ms and errors) and the safe ones stay in tens of milliseconds with no errors and no stalled second. Run `make run` when the machine is quiet, and read the last column of `results.md`, to see where your machine lands. `test_step3_...` bracket-measures the baseline before and after the migration and passes on a quiet machine; it can fail on a busy one.


| Done when (lesson) | How to see it | Test |
|---|---|---|
| **Step 1.** The load runs at a steady rate for ten minutes with stable p99. | `BASELINE_SECONDS=600 make run`: the opening baseline row of `results.md` (rate, errors, p99 over 600 s). `make load SECONDS=600` prints it second by second. | `test_step1_the_load_holds_a_steady_rate_with_stable_p99` (12 seconds, three windows) |
| **Step 2.** The lock views show the `ALTER` waiting behind the long transaction and every new query from the load waiting behind the `ALTER`, and you can explain why reads stopped although the `ALTER` had not started. | `sql/explain/lock_queue.txt`: the `ALTER` is blocked by the reader's pid, every load statement is blocked by the `ALTER`'s pid, and the `ALTER`'s `AccessExclusiveLock` is `granted = f`. The explanation (requests are granted in arrival order per table) is in [ARCHITECTURE.md](ARCHITECTURE.md). | `test_step2_the_alter_waits_behind_a_long_read_and_the_load_waits_behind_the_alter` |
| **Step 3.** The migration completes while the load's p99 stays within twice its baseline, and a forced lock conflict makes the migration step fail fast instead of waiting in the lock queue. | The "safe migration" row of `results.md` (last column) and the "Forced conflict" line: the `ALTER` gave up at its 1 s `lock_timeout`. | `test_step3_safe_migration_keeps_p99_within_twice_baseline_and_a_forced_conflict_fails_fast`, `test_step3_a_failed_attempt_retries_instead_of_giving_up` |
| **Step 4.** Writes keep flowing during the build, and you have found and cleaned up an invalid index left by a build you interrupted on purpose. | "CREATE INDEX CONCURRENTLY" row: no errors, slowest operation a fraction of the plain build's. The "Step 4" section names the invalid index found in `pg_index` and the rebuild. | `test_step4_a_plain_index_build_stalls_writes_and_a_concurrent_one_does_not`, `test_step4_an_interrupted_concurrent_build_leaves_an_invalid_index_that_is_found_and_dropped` |
| **Step 5.** No step blocks the load for more than a moment, and your notes say which lock each step held. | The "Step 5" table of `results.md`: the lock mode and duration of each move, from `pg_locks` inside the move's own transaction. | `test_step5_not_null_in_three_moves_holds_each_lock_only_briefly` |
| **Step 6.** You have plans showing the bad row estimate and the bad scan choice, then the corrected estimate and plan, and the README explains how you would prevent it. | `f1_stale_statistics.txt` (estimate 1, actual 150,000, `Seq Scan` and `Sort`), `f2_after_analyze.txt`, `f3_after_extended_statistics.txt`; prevention below. | `test_step6_a_plan_flips_on_stale_statistics_and_is_fixed_by_extended_statistics` |
| **Diagram.** p99 stays within twice its baseline; a forced conflict fails fast. | The two rows above (steps 3). | |

`test_the_lab_resets_to_the_seed` checks that every experiment can be undone, so `make run` and `make test` can follow each other.

### How to prevent the plan flip

- **Analyze after a bulk load.** Autovacuum analyzes a table when about 10% of its rows have changed (the default scale factor is 0.1, plus 50 rows). A load smaller than that, or one that runs before autovacuum wakes up, leaves the planner with old statistics. A job that loads a month of data should end with `ANALYZE events`, not wait for autovacuum.
- **Lower the threshold for big tables.** `ALTER TABLE events SET (autovacuum_analyze_scale_factor = 0.01)` makes autovacuum analyze after 1% change.
- **Tell the planner about correlated columns.** `CREATE STATISTICS ... (dependencies, mcv) ON region, city` for columns that are queried together. Check `pg_stats_ext` after the next `ANALYZE`.
- **Watch estimate error, not only time.** Compare `rows=` with `actual rows=` in plans of important queries (for example with `auto_explain` and `log_analyze` for slow ones), and rank queries by `mean_exec_time` change in `pg_stat_statements` after each deploy and each big load.
- **Prefer a query that does not depend on the estimate.** Here an extra bound on `created_at` makes the index plan the only sensible one even with a wrong estimate.

## Stretch goals

| Stretch | Built? |
|---|---|
| Partition the table by month and attach a new partition without blocking the load | No. Sketch in [ARCHITECTURE.md](ARCHITECTURE.md), "How to extend it". |
| Compare a batched backfill with a single `UPDATE` on lock time, WAL volume and replica lag | No. |
| Pin a good plan or use a planner hint extension, and argue for or against it | No. |
| Repeat step 4 on MySQL and compare its online DDL | No. |

## What is simplified for teaching

- **2,000,000 rows, not 50,000,000.** Every effect shows at this size, in shorter windows: the plain index build stalls writes for under a second here, the NOT NULL scan for about half a second. `ROWS=50000000` gives the lesson's size, with proportionally longer stalls, a backfill of about an hour and about 12 GB of disk. The default was chosen so that the whole lab, including its tests, runs in minutes on a laptop; the full size was not run for this repository.
- **Reads use an index on `created_at` that exists from the start.** The lesson reads with a predicate on `created_at`; without an index that scans the table, and its 14 ms baseline implies there is one. The lesson's own index is `(device_id, created_at DESC)`, added in step 4.
- **The naive index and NOT NULL run on the real table**, not on a copy, and are undone straight away (the index is dropped, the scratch column removed). The load sees exactly what it would see in production.
- **Extended statistics add `mcv` to the lesson's `dependencies`.** `dependencies` alone lifts the estimate from 1 to about 60,000 against 150,000 actual; adding `mcv` brings it to about 150,000. See [ARCHITECTURE.md](ARCHITECTURE.md).
- **Autovacuum is switched off for `events` during the plan-flip experiment**, so it cannot repair the statistics before the query is planned, and switched back on afterwards.
- **The baseline is 60 seconds by default** (600 for the lesson's ten minutes). The tests use 8-second windows, bracketing each change with a baseline before and after.
- **p99 is noisy on a shared machine.** The tests compare against the higher of two baselines, taken before and after the change, because other work on the machine moves p99 as much as the backfill does. If `results.md` says "no" in the last column of the safe-migration row, check whether the closing baseline is far above the opening one and run again when the machine is quiet.
- **The backfill batch is 2,000 rows, not the lesson's 10,000.** From a fresh database, 10,000-row batches gave the load the highest p99 in both rounds of the committed sweep (`sql/explain/backfill-sweep.txt`): each batch writes a burst of WAL and the inserts' commits queue behind it (the load's sessions were waiting on `WalSync`, `WALWrite` and `WalInit*`). Smaller batches are gentler but not immune (one of the two 2,000-row arms was at twice its baseline), and p99 on a shared laptop moves a lot from run to run, so `make sweep` measures the arms again from fresh databases. The lesson's number is a starting point: the right size is the largest one that keeps p99 inside the bar. Larger batches finish the backfill sooner, and on a server with different disks and WAL settings the answer will differ.
- **A plain Python load script**, four connections, one statement per transaction, 3 s statement timeout. Real traffic has pools, longer transactions and retries.
- **Throwaway credentials** (`lab`/`lab`) on a port only your machine can reach.

## Troubleshooting

- `port is already allocated`: another process uses 55433. Set `PGPORT` in `.env`.
- `make run` or `make test` fails with a connection error: run `make up` and `make db` first.
- A run was interrupted and left a session open: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name IN ('long-transaction', 'naive-alter', 'index-build');` in `make psql`. The next `make run` or test starts by removing anything the lab added.
- The load shows `errors` while you try a naive statement: that is the point; operations time out after 3 seconds.

## Author and license

Written by Sumit Srivastava. Released under the MIT License, see [LICENSE](LICENSE).

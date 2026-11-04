# SQL optimization: locks and migration

A busy PostgreSQL 18 table under constant read and write load from a script, and the three changes you must make to it while the load keeps running: add a column and backfill it, add an index, and make the column `NOT NULL`. You first do each the naive way and watch what blocks, then do it safely, then cause a plan regression with stale and missing statistics and fix it.

This repository is the runnable build of the Plainround lesson **"Change a huge busy table without blocking it"** (`/prep/sql-optimization/project-locks-and-migration`, planned at **14 hours**). It uses PostgreSQL, the engine the lesson names for the lock experiments.

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/architecture-dark.svg">
  <img alt="A load script, a long transaction and a migration all reach the events table in PostgreSQL 18. The long transaction holds ACCESS SHARE, the migration needs ACCESS EXCLUSIVE and waits for it in amber, and the load queues behind the migration. Statistics are sampled from events by ANALYZE." src="docs/diagrams/architecture.svg">
</picture>

Notice that the migration never blocks anything on its own: it waits behind session A, and every write waits behind the migration.

## How one run flows

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/flow-dark.svg">
  <img alt="One make run in seven steps. The load keeps running while a naive ALTER queues behind a long read in amber, then the safe migration, the index, NOT NULL in three moves and the plan flip run without a stall." src="docs/diagrams/flow.svg">
</picture>

The amber row is step 2, the lock queue; the green box is the closing verdict that p99 stayed within twice the baseline.

## What is in it

| Piece | Where |
|---|---|
| PostgreSQL 18 in Docker | `docker-compose.yml` |
| Schema (DDL), seed (DML), the inspection queries the lesson uses | `sql/001_schema.sql`, `sql/002_seed.sql`, `sql/003_queries.sql` |
| The safe changes, one file per step, each with a down script | `sql/migrations/001` to `006`, `sql/migrations/down/` |
| The three naive statements, to run by hand | `sql/naive/` |
| The plan-flip data load | `sql/experiments/` |
| The plans of the flip (`.sql` to run, `.txt` captured), the lock queue snapshot, and the numbers | `sql/explain/` |
| The load script (steady inserts, updates and reads; p99 and errors every second) | `src/locks_lab/infrastructure/load_runner.py`, `locks-lab-load` |
| The safe-migration tools: retry on `lock_timeout`, batched backfill, lock report, interrupted-build helper | `src/locks_lab/infrastructure/schema_changes.py` |
| Each experiment as a use case, and the replay that chains them | `src/locks_lab/application/scenarios.py`, `replay.py`, `locks-lab-run` |
| Tests at three levels, one per "Done when" line | `tests/unit`, `tests/integration`, `tests/e2e` |
| How it fits together, and why | [ARCHITECTURE.md](ARCHITECTURE.md), [docs/adr/](docs/adr/) |

## Project structure

```text
.
├── src/locks_lab/            the Python package (pattern: ports and adapters in four layers)
│   ├── domain/               pure rules and values: p99 and window statistics, the lock-queue model,
│   │                         backfill id ranges, plan-flip parsing, outcomes, host load. No I/O.
│   ├── application/          the use cases (each experiment, the replay, the health check) and the ports
│   │                         they need (database, load, files). No psycopg, no threads.
│   ├── infrastructure/       the adapters: PostgreSQL, the threaded load, the SQL file runner, files,
│   │                         settings, logging, retry with backoff, graceful shutdown
│   └── interfaces/           the commands: locks-lab-run, locks-lab-load, locks-lab-health; the composition root
├── tests/
│   ├── unit/                 no database; domain and application coverage gate at 95%
│   ├── integration/          the lesson's outcomes against PostgreSQL with the load running
│   └── e2e/                  the commands, end to end
├── sql/                      what you run by hand and what the program runs
│   ├── 001_schema.sql        002_seed.sql  003_queries.sql  reset.sql
│   ├── migrations/           001 to 006: the safe changes; down/ holds the way back for each
│   ├── naive/                the three statements that block, to try in make psql
│   ├── experiments/          the correlated bulk load for the plan flip
│   └── explain/              captured plans, the lock queue and results.md written by make run / make measure
├── docs/adr/                 architecture decision records
├── Dockerfile                the container image of the commands (non-root)
├── docker-compose.yml        PostgreSQL 18 for the lab
├── pyproject.toml            package, tool configuration, import-linter contracts
├── requirements.lock         hashed, pinned runtime dependencies
├── requirements-dev.lock     hashed, pinned development dependencies
├── Makefile                  up, db, run, measure, test, lint, down (make help lists all)
├── .github/workflows/ci.yml  checks and audit; integration and end-to-end tests with a PostgreSQL 18 service
├── CHANGELOG.md  .editorconfig  .gitignore  .dockerignore  LICENSE
└── ARCHITECTURE.md  README.md
```

The dependency rule is the layer order: `interfaces` imports `infrastructure`, `infrastructure` imports `application`, `application` imports `domain`, and nothing imports the other way. `lint-imports` (part of `make lint`) fails on a violation, and a second contract keeps `psycopg` and `threading` out of `domain` and `application`.

## Prerequisites

| Tool | Version used | Notes |
|---|---|---|
| Docker with Compose v2 | Docker 24 or newer | Runs PostgreSQL. No local PostgreSQL or `psql` needed. |
| Python | 3.12 or newer (tested on 3.13) | Runs the load, the migrations and the tests in a virtual environment (`.venv/`, built from the lock file). |
| make | any | |
| PostgreSQL | **18** (`postgres:18`) | The track assumes PostgreSQL 18 as of October 2026. The lock modes and `NOT VALID` behavior used here are the same from PostgreSQL 12. |

Free disk: about 2 GB at the default size (the table grows to about 400 MB during the backfill, plus WAL). Memory: 512 MB of shared buffers and 768 MB of shared memory in the container. Port 55433.

## Setup, run, test, stop

```bash
cp .env.example .env   # one-time: PGPASSWORD has no default on purpose (use any throwaway value)
```

```bash
make up      # start PostgreSQL 18 on localhost:55433 and wait until it is healthy
```

```bash
make db      # schema, then 2,000,000 events (about 10 seconds), then the lesson's inspection queries
```

```bash
make run     # replay the lesson with the load running throughout: about 5 minutes with a 20-second baseline
```

```bash
make test    # unit tests with coverage, no database needed (about 5 seconds)
```

```bash
make test-integration test-e2e   # the lesson's outcomes with the load running, then the commands end to end (about 8 minutes)
```

```bash
make lint    # ruff, ruff format check, mypy strict, import-linter
```

```bash
make down    # stop PostgreSQL and delete its volume
```

Settings (all optional):

- `make measure` replays with the lesson's ten-minute baseline (`MEASURE_SECONDS=600`). Use it for figures you quote; `make run` is the short version.
- `ROWS=50000000 make db` builds the lesson's 50,000,000-row table (about 12 GB on disk). The default is 2,000,000: every lock effect is the same, the stalls are shorter.
- `BACKFILL_BATCH=10000 make run` uses the lesson's backfill batch size; the default is 2,000 rows with a 0.05 s pause (see "What is simplified for teaching").
- `make load SECONDS=120` runs the load script alone and prints its one-second lines, which is the way to watch the table while you try the naive statements from `sql/naive/` in `make psql` sessions.
- `make health` exits 0 when PostgreSQL holds the seeded table, 1 when it does not (unreachable or not seeded), 2 when the settings are unusable (for example `PGPASSWORD` unset).

`make run` and `make measure` rewrite `sql/explain/results.md`, `lock_queue.txt` and the `f*.txt` plans, and write `load-metrics.jsonl` (ignored by git), one record per second with the step names marked in it. The first lines of `results.md` say how busy the machine was.

## What the build does

| Step | What happens | Where to see it |
|---|---|---|
| 1 | The load runs for the baseline period: 40 iterations a second of insert, update of a recent row, and read of recent events (120 operations a second). | `results.md`, "baseline" rows |
| 2 | A session reads and stays open. A naive `ALTER TABLE ... ADD COLUMN` waits for it, and the load's inserts wait for the `ALTER`. | `lock_queue.txt`, step 2 of `results.md` |
| 3 | The safe version: `lock_timeout` with retry, the column without a rewrite, a batched backfill (2,000 rows at a time by default, the lesson starts at 10,000) with a pause. A forced conflict makes it fail fast. | `results.md` |
| 4 | A plain `CREATE INDEX` stalls writes; `CREATE INDEX CONCURRENTLY` does not. A build cancelled on purpose leaves an invalid index that is found and dropped. | `results.md` |
| 5 | `NOT NULL` in three moves, each with the lock it held. | `results.md` |
| 6 | A correlated month is loaded; the query is planned before statistics catch up, after `ANALYZE`, and after extended statistics. | `f1_*.txt`, `f2_*.txt`, `f3_*.txt` |

## Done when: how each line is proved

**Measured at load average 3.0 on 12 CPUs, on 2026-11-02.** These numbers come from `sql/explain/results.md`, the last `make measure` (ten-minute baseline), taken on a quiet machine. The baseline p99 is 7.1 ms; on a busy shared laptop the same run gave a baseline of 73 ms, so always read the load average at the top of `results.md` before comparing milliseconds. The before-and-after ratios survive load far better than the milliseconds.

| Change | Naive: p99 ms (errors, stalled seconds) | Safe: p99 ms (errors, stalled seconds) | Ratio |
|---|---:|---:|---:|
| Add a column (naive `ALTER` behind a long read, then add column and backfill) | 3,003 (4, 6) | 4.9 (0, 0) | 614x |
| Add an index (plain, then `CONCURRENTLY`) | 691 (0, 0) | 128 (0, 0) | 5.4x |
| `NOT NULL` (one `SET NOT NULL`, then three moves) | 142 (0, 0) | 6.6 (0, 0) | 22x |
| The plan after a bulk load (stale statistics, then extended statistics), execution time | 160 ms | 0.79 ms | about 200x |

| Window | p99 ms | Max ms | Errors | Stalled seconds |
|---|---:|---:|---:|---:|
| Baseline, opening (600 s, 120 operations a second) | 7.1 | 249 | 0 | 0 |
| Baseline, closing (20 s) | 6.4 | 19.9 | 0 | 0 |
| Naive `ALTER` behind a long read (6 s) | 3,003 | 3,003 | 4 | 6 |
| Safe migration: column and 1,013 backfill batches (83 s) | 4.9 | 68.5 | 0 | 0 |
| Plain `CREATE INDEX` (0.8 s build) | 691 | 693 | 0 | 0 |
| `CREATE INDEX CONCURRENTLY` (1.0 s build) | 128 | 130 | 0 | 0 |
| Naive `SET NOT NULL` (187 ms scan) | 142 | 144 | 0 | 0 |
| `NOT NULL` in three moves | 6.6 | 8.3 | 0 | 0 |

The safe migration's p99 (4.9 ms) is below the higher baseline (7.1 ms), so the "within twice baseline, no errors, no stalled second" line is met in this run. Locks held by the three `NOT NULL` moves: `ACCESS EXCLUSIVE` for 3.6 ms, `SHARE UPDATE EXCLUSIVE` for 158 ms (the validation scan, with reads and writes flowing), `ACCESS EXCLUSIVE` for 1.2 ms. The plan flip: estimate 1 row against 150,000 found (160 ms, `Seq Scan` and `Sort`); after `ANALYZE` an estimate of 34,127 and the index plan (1.07 ms); after extended statistics an estimate of 148,932 (0.79 ms).

**What this run shows and what it does not.** The concurrent build's slowest operation (130 ms) is above twice the baseline's p99 (14.2 ms), so the strict last column of `results.md` says "no" for it; the lesson asks that line only of the safe migration, and the test for step 4 compares the slowest insert with the length of the build itself, which load does not change. The plain build took only 0.8 s here, so the damage is one slow operation (693 ms) rather than seconds of stall; on a larger table it grows with the length of the build. Between runs on a shared laptop the p99 of single-millisecond statements moves by a factor of two or three, and the backfill's cost sits near the bar: earlier runs kept the safe migration at 10 to 16 ms against baselines of 3 to 7 ms, and once missed the factor of two (17.8 ms against a bar of 8.0 ms). The lab shows the order of magnitude reliably: the naive changes stall the load or add hundreds of milliseconds, and the safe ones stay within a few multiples of the baseline with no errors and no stalled second. One earlier run on 2026-11-02 under load (load average 13.1 on 12 CPUs) gave a safe-migration p99 of 33.2 ms against a bar of 16.0 ms: it missed the factor of two, which is why the load average printed at the top of `results.md` matters.


| Done when (lesson) | How to see it | Test |
|---|---|---|
| **Step 1.** The load runs at a steady rate for ten minutes with stable p99. | `make measure`: the opening and closing baseline rows of `results.md` (rate, errors, p99 over 600 s). `make load SECONDS=600` prints it second by second. | `test_step1_the_load_holds_a_steady_rate_with_stable_p99` (three windows) |
| **Step 2.** The lock views show the `ALTER` waiting behind the long transaction and every new query from the load waiting behind the `ALTER`, and you can explain why reads stopped although the `ALTER` had not started. | `sql/explain/lock_queue.txt`: the `ALTER` is blocked by the reader's pid, every load statement is blocked by the `ALTER`'s pid, and the `ALTER`'s `AccessExclusiveLock` is `granted = f`. The explanation (requests are granted in arrival order per table) is in [ARCHITECTURE.md](ARCHITECTURE.md). | `test_step2_the_alter_waits_behind_a_long_read_and_the_load_waits_behind_the_alter` |
| **Step 3.** The migration completes while the load's p99 stays within twice its baseline, and a forced lock conflict makes the migration step fail fast instead of waiting in the lock queue. | The "safe migration" row of `results.md` (last column) and the "Forced conflict" line: the `ALTER` gave up at its `lock_timeout`. | `test_step3_the_safe_migration_keeps_p99_within_twice_baseline_and_a_forced_conflict_fails_fast`, `test_step3_a_failed_attempt_retries_instead_of_giving_up` |
| **Step 4.** Writes keep flowing during the build, and you have found and cleaned up an invalid index left by a build you interrupted on purpose. | "CREATE INDEX CONCURRENTLY" row: no errors, slowest operation a fraction of the plain build's. The "Step 4" section names the invalid index found in `pg_index` and the rebuild. | `test_step4_a_plain_index_build_stalls_writes_and_a_concurrent_one_does_not`, `test_step4_an_interrupted_concurrent_build_leaves_an_invalid_index_that_is_found_and_dropped` |
| **Step 5.** No step blocks the load for more than a moment, and your notes say which lock each step held. | The "Step 5" table of `results.md`: the lock mode and duration of each move, from `pg_locks` inside the move's own transaction. | `test_step5_not_null_in_three_moves_holds_each_lock_only_briefly`, `test_step5_the_column_ends_not_null_and_the_helper_constraint_is_gone` |
| **Step 6.** You have plans showing the bad row estimate and the bad scan choice, then the corrected estimate and plan, and the README explains how you would prevent it. | `f1_stale_statistics.txt` (estimate 1, actual 150,000, `Seq Scan` and `Sort`), `f2_after_analyze.txt`, `f3_after_extended_statistics.txt`; prevention below. | `test_step6_a_plan_flips_on_stale_statistics_and_is_fixed_by_extended_statistics` |
| **Diagram.** p99 stays within twice its baseline; a forced conflict fails fast. | The step 3 row above. | |
| **Production grade.** Every script runs twice without harm; every migration has a way back. | `sql/migrations/down/`; `make db` twice changes nothing. | `test_migrations_run_twice_and_revert_twice_in_reverse_order_without_harm`, `test_the_schema_and_seed_scripts_can_run_twice`, `test_the_lab_resets_to_the_seed` |

### How to prevent the plan flip

- **Analyze after a bulk load.** Autovacuum analyzes a table when about 10% of its rows have changed (the default scale factor is 0.1, plus 50 rows). A load smaller than that, or one that runs before autovacuum wakes up, leaves the planner with old statistics. A job that loads a month of data should end with `ANALYZE events`, not wait for autovacuum.
- **Lower the threshold for big tables.** `ALTER TABLE events SET (autovacuum_analyze_scale_factor = 0.01)` makes autovacuum analyze after 1% change.
- **Tell the planner about correlated columns.** `CREATE STATISTICS ... (dependencies, mcv) ON region, city` for columns that are queried together. Check `pg_stats_ext` after the next `ANALYZE`.
- **Watch estimate error, not only time.** Compare `rows=` with `actual rows=` in plans of important queries (for example with `auto_explain` and `log_analyze` for slow ones), and rank queries by `mean_exec_time` change in `pg_stat_statements` after each deploy and each big load.
- **Prefer a query that does not depend on the estimate.** Here an extra bound on `created_at` makes the index plan the only sensible one even with a wrong estimate.

## Quality bar

| Concern | How it is met |
|---|---|
| Design | Ports and adapters in four layers; the rule is enforced by import-linter. See [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/adr/](docs/adr/). |
| Types, format, lint | mypy strict, ruff check and format in `make lint` and CI. |
| Tests | Unit (no database, coverage gate of 95% on domain and application, reported on every run), integration (PostgreSQL 18 with the load running), one end-to-end test of the whole replay. |
| Logging | Structured `key=value` lines on stderr (`LOG_LEVEL` to change the level); results go to stdout and to files. |
| Health | `make health` / `locks-lab-health`; the container image has a `HEALTHCHECK`. |
| Shutdown | SIGINT and SIGTERM stop the load and the experiment at the next safe point, release the lab's sessions and exit 130. |
| Timeouts and retries | Every connection and statement has a timeout; connecting retries with exponential backoff and jitter; the migration retries on `lock_timeout`. |
| Secrets | Only from the environment. `PGPASSWORD` has no default; the compose file refuses to start without it. |
| Dependencies | Hashed lock files; `make audit` runs `pip-audit` on them in CI. |
| SQL | Every script runs twice without harm; each migration has a down script; migrations that need a lock set `lock_timeout` themselves. |

## Stretch goals

| Stretch | Built? |
|---|---|
| Partition the table by month and attach a new partition without blocking the load | No. Sketch in [ARCHITECTURE.md](ARCHITECTURE.md), "How to extend it". |
| Compare a batched backfill with a single `UPDATE` on lock time, WAL volume and replica lag | No. |
| Pin a good plan or use a planner hint extension, and argue for or against it | No. |
| Repeat step 4 on MySQL and compare its online DDL | No. |

## What is simplified for teaching

- **2,000,000 rows, not 50,000,000.** Every effect shows at this size, in shorter windows: the plain index build stalls writes for under a second here, the NOT NULL scan for a fraction of one. `ROWS=50000000` gives the lesson's size, with proportionally longer stalls, a backfill of about an hour and about 12 GB of disk. The full size was not run for this repository.
- **Reads use an index on `created_at` that exists from the start.** The lesson reads with a predicate on `created_at`; without an index that scans the table, and its 14 ms baseline implies there is one. The lesson's own index is `(device_id, created_at DESC)`, added in step 4.
- **The naive index and NOT NULL run on the real table**, not on a copy, and are undone straight away (the index is dropped, the scratch column removed). The load sees exactly what it would see in production.
- **Extended statistics add `mcv` to the lesson's `dependencies`.** `dependencies` alone lifts the estimate from 1 to about 60,000 against 150,000 actual; adding `mcv` brings it to about 150,000. See [ARCHITECTURE.md](ARCHITECTURE.md).
- **Autovacuum is switched off for `events` during the plan-flip experiment**, so it cannot repair the statistics before the query is planned, and switched back on afterwards.
- **The baseline is 20 seconds with `make run`** (600 with `make measure`, the lesson's ten minutes). The integration tests use short windows, bracketing each change with a baseline before and after.
- **p99 is noisy on a shared machine.** The tests and the report compare against the higher of two baselines, taken before and after the change, because other work on the machine moves p99 as much as the backfill does. `results.md` records the load average of the machine, and the figures above say which load they were taken under.
- **The backfill batch is 2,000 rows, not the lesson's 10,000.** Each batch writes a burst of WAL and the inserts' commits queue behind it (the load's sessions wait on `WalSync` and `WALWrite`); the larger the batch, the larger the burst. The lesson's number is a starting point: the right size is the largest one that keeps p99 inside the bar, and on a server with different disks and WAL settings the answer will differ. The default is a measurement, not a rule ([docs/adr/0002](docs/adr/0002-backfill-batch-size-is-a-measurement.md)). The compose file spaces out checkpoints (`max_wal_size=8GB`, `checkpoint_timeout=15min`) so that one does not start in the middle of a window.
- **A plain Python load script**, four connections, one statement per transaction, 3 s statement timeout. Real traffic has pools, longer transactions and retries.
- **Throwaway credentials** in `.env` on a port only your machine can reach.

## Troubleshooting

- `port is already allocated`: another process uses 55433. Set `PGPORT` in `.env`.
- `PGPASSWORD` error from compose: copy `.env.example` to `.env`.
- `make run` or the integration tests fail with a connection error: run `make up` and `make db` first, and check `make health`.
- A run was interrupted and left a session open: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name IN ('long-transaction', 'naive-alter', 'index-build');` in `make psql`. The next run starts by removing anything the lab added.
- The load shows `errors` while you try a naive statement: that is the point; operations time out after 3 seconds.
- Results look noisy: look at the load average at the top of `results.md`, and rerun `make measure` when the machine is quiet.

## Author and license

Written by Sumit Srivastava. Released under the MIT License, see [LICENSE](LICENSE).

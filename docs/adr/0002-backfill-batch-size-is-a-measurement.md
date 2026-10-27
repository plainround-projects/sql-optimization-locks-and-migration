# 0002. The backfill batch size is a measurement, not a constant

Status: accepted, 2026-10-27

## Context

The lesson starts the backfill at 10,000 rows per batch with a pause. On this laptop-sized lab, from a freshly loaded database, 10,000-row batches gave the load the highest p99 in both rounds of the sweep (`sql/explain/backfill-sweep.txt`): each batch writes its WAL in one burst and the load's commits queue behind the flush. 5,000 and 2,000 rows were gentler but not immune, and p99 on a shared machine moves by a factor of two or three between runs.

## Decision

The default is 2,000 rows with a 0.05 s pause, configurable (`BACKFILL_BATCH`, `BACKFILL_PAUSE_SECONDS`). Comparisons of batch sizes start every arm from a fresh database, because the first pass over a freshly loaded table is the expensive one. The README and results say which size was used.

## Consequences

- The lesson's number is kept as the documented starting point; the repository's number is the one that was measured to be gentlest here.
- Larger batches finish sooner; the right size on a production server with different disks and WAL settings has to be measured there.
- The backfill is idempotent (`WHERE flagged IS NULL`), so changing the size mid-way or stopping on SIGTERM loses nothing.

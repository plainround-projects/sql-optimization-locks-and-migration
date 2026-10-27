# 0001. Each experiment is a use case over ports; threads and locks stay in adapters

Status: accepted, 2026-10-27

## Context

The lab needs a steady load (threads, connections, timers), sessions that hold locks, DDL under lock timeouts, and a lot of arithmetic about latency windows. The first version was a set of scripts that mixed all of it, so the interesting rules (what counts as a stalled second, what "within twice the baseline" means, how a backfill is cut into batches) were only checked by running a ten-minute experiment.

## Decision

- `domain/` holds the rules as pure values and functions: percentiles, tick and window summaries, the p99 `Bar`, id ranges for a batched backfill, lock snapshots, plan estimates. It imports neither PostgreSQL nor `threading`; import-linter enforces both.
- `application/scenarios.py` has one method per experiment of the lesson, over small ports (`LoadGenerator`, `LockExperiments`, `SchemaChanges`, `PlanFlipLab`, `LabTable`). `ReplayLesson` chains them.
- `infrastructure/` implements the ports: `ThreadedLoad`, the long-transaction and ALTER sessions, the migration files run under retry, the plan-flip data load.

## Consequences

- The verdict logic is unit-tested with scripted windows; the experiments' orchestration is unit-tested with fakes; only the adapters need a database.
- A second implementation of a port (for MySQL's online DDL, for example) is a new adapter, not a rewrite.
- The ports pass durations and callbacks (`pause`, `should_stop`) so tests run instantly and a SIGTERM stops the backfill between batches.

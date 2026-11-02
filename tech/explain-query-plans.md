# EXPLAIN and reading query plans

## What it is

A **query plan** is the step-by-step method PostgreSQL chooses to answer an SQL statement: which tables to read, in what way, which indexes to use, how to sort and combine. **`EXPLAIN`** prints the plan instead of (or as well as) running the statement. Reading plans is the central skill of this lesson: a plan tells you *why* a query is slow.

## Why this repository uses it

Only the plan-flip experiment uses plans: it captures the same query's plan three times and reads the planner's row estimate from each. The point is to see a wrong guess and a corrected guess in the planner's own output.

## Where it appears

| File | Role |
|---|---|
| `sql/explain/f1_stale_statistics.sql` / `.txt`, `f2_after_analyze`, `f3_after_extended_statistics` | The `EXPLAIN (ANALYZE, BUFFERS)` statements and their captured output. |
| `src/locks_lab/domain/flip.py` | Reads the estimate, the node types and the time. |
| `src/locks_lab/infrastructure/plan_flip.py` | Runs the three captures. |
| `sql/explain/results.md` | The table built from them. |

## How it works underneath

**Variants.**

- `EXPLAIN SELECT ...` shows the plan the planner *would* use, with **estimates** (a guess based on statistics). The statement is not run.
- `EXPLAIN ANALYZE SELECT ...` **runs** the statement and adds **actual** numbers. Because it really executes, an `INSERT`, `UPDATE` or `DELETE` really happens; wrap it in a transaction and `ROLLBACK` to undo.
- Options go in brackets: `EXPLAIN (ANALYZE, BUFFERS, WAL, SERIALIZE, FORMAT JSON) ...`.
  - `BUFFERS` adds page counts: `shared hit=` (found in PostgreSQL's cache), `read=` (not found there, fetched from the operating system or disk), `dirtied=`, `written=`.
  - `WAL` adds write-ahead-log volume for statements that write: `WAL: records=... bytes=...`.
  - `SERIALIZE` (PostgreSQL 17 and newer) also measures the work of converting the result rows to the text sent to the client, including fetching out-of-line (TOAST) values; it adds a `Serialization:` line.
  - `FORMAT JSON` prints the same information as a JSON document, which programs parse easily.

**A plan is a tree.** The text is indented: the top line is the last step, which produces the result; lines starting with `->` are child steps feeding it. Data flows from the deepest steps up. Each step is a **node**.

**What each node line says.**

```text
Seq Scan on orders  (cost=0.00..78758.28 rows=5003 width=457) (actual time=0.455..830.145 rows=2748.00 loops=1)
```

- `Seq Scan on orders`: the node type and the table.
- `cost=0.00..78758.28`: the planner's estimate in arbitrary cost units: before the first row, and for all rows.
- `rows=5003`: *estimated* rows out of this node. `width=457`: estimated bytes per row.
- `actual time=0.455..830.145`: milliseconds until the first row and until the last row.
- `rows=2748.00`: *actual* rows (PostgreSQL 18 prints a fraction). If this differs by a lot from the estimate, the statistics are poor.
- `loops=1`: how many times the node ran; times and rows are per loop.

**Lines under a node.** `Filter:` (a condition applied to each row after reading it), `Rows Removed by Filter:` (rows read and thrown away: a high number is wasted work), `Index Cond:` (a condition handled by the index), `Recheck Cond:`, `Sort Key:`, `Sort Method:` (`quicksort`, `top-N heapsort`: keeping only the best N rows, `external merge`: spilled to disk), `Heap Blocks:`, `Heap Fetches:` (table visits made by an index-only scan), `Index Searches:` (how many separate descents of the index tree; PostgreSQL 18), `Buffers:`, `I/O Timings:` (time waiting for reads; needs `track_io_timing = on`).

**The footer.** `Planning Time:` (time choosing the plan), `Serialization:` (time and size of the output), `Execution Time:` (total, in milliseconds).

**How to read one.**

1. Start at the deepest node: how is the table read (`Seq Scan`, `Index Scan`...)?
2. Compare estimated and actual rows at each node.
3. Look for wasted work: `Rows Removed by Filter`, a `Sort` where an index could provide order, large `Buffers`.
4. Compare *pages touched* (hit + read), which does not depend on the machine's speed, as well as milliseconds, which does.

## Walkthrough of this repository's use

`sql/explain/f1_stale_statistics.sql`, lines 1 to 4:

```sql
-- Step 6 before: the new month is loaded but statistics have not caught up. The planner has never seen 'pacific' or 'seattle' and expects one row.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, created_at FROM events WHERE region = 'pacific' AND city = 'seattle' ORDER BY created_at DESC LIMIT 100;
```

The file is a comment, `SET timezone = 'UTC'`, and the `EXPLAIN (ANALYZE, BUFFERS)` of the query. `ANALYZE` runs it for real (it is a `SELECT`, so nothing changes); `BUFFERS` adds page counts.

`sql/explain/f1_stale_statistics.txt`, lines 1 to 13:

```text
Limit  (cost=80154.85..80154.85 rows=1 width=16) (actual time=160.418..160.426 rows=100.00 loops=1)
  Buffers: shared hit=39116 read=10990 written=254
  ->  Sort  (cost=80154.85..80154.85 rows=1 width=16) (actual time=160.417..160.420 rows=100.00 loops=1)
        Sort Key: created_at DESC
        Sort Method: top-N heapsort  Memory: 32kB
        Buffers: shared hit=39116 read=10990 written=254
        ->  Seq Scan on events  (cost=0.00..80154.84 rows=1 width=16) (actual time=0.111..144.397 rows=150000.00 loops=1)
              Filter: ((region = 'pacific'::text) AND (city = 'seattle'::text))
              Rows Removed by Filter: 2453908
              Buffers: shared hit=39113 read=10990 written=254
Planning:
  Buffers: shared hit=29 read=2
Planning Time: 0.199 ms
```

Reading it, outermost step first:

1. `Limit  (cost=80154.85..80154.85 rows=1 width=16) (actual time=160.418..160.426 rows=100.00 loops=1)`: keep 100 rows. The planner **estimated 1 row** (`rows=1`); it actually produced 100.
2. `->  Sort  (...) Sort Key: created_at DESC  Sort Method: top-N heapsort  Memory: 32kB`: sort by time, newest first, keeping only the best 100 (a "top-N heapsort" uses little memory).
3. `->  Seq Scan on events  (cost=0.00..80154.84 rows=1 width=16) (actual time=0.111..144.397 rows=150000.00 loops=1)`: read the whole table. Estimate: 1 row. Actual: **150,000**. This gap is the whole story.
4. `Filter: ((region = 'pacific'::text) AND (city = 'seattle'::text))` and `Rows Removed by Filter: 2453908`: 2.45 million rows read and discarded.
5. `Buffers: shared hit=39113 read=10990`: pages touched (some from outside the cache: `read=`).
6. `Planning:` / `Buffers: shared hit=29 read=2` is the work of planning itself (PostgreSQL 17 and newer print it), then `Planning Time: 0.199 ms` and `Execution Time: 160.440 ms`.

`sql/explain/f2_after_analyze.txt`, lines 1 to 8:

```text
Limit  (cost=0.43..863.80 rows=100 width=16) (actual time=1.011..1.054 rows=100.00 loops=1)
  Buffers: shared hit=3894 read=18
  ->  Index Scan Backward using idx_events_created_at on events  (cost=0.43..294643.30 rows=34127 width=16) (actual time=1.010..1.048 rows=100.00 loops=1)
        Filter: ((region = 'pacific'::text) AND (city = 'seattle'::text))
        Rows Removed by Filter: 4217
        Index Searches: 1
        Buffers: shared hit=3894 read=18
Planning:
```

After `ANALYZE`: `Index Scan Backward using idx_events_created_at` under the `Limit`. The scan's estimate is `rows=34127` but it stops after 100 rows (`actual ... rows=100.00`): `Rows Removed by Filter: 4217` — it walked 4,317 index entries to find 100 Seattle rows. `Index Searches: 1`, 3,912 buffers, 1.065 ms in the committed file. The Python reader, `parse_flip_plan`, takes the last `rows=` of the plan as the estimate (regular-expressions note) and the node types in order.

`src/locks_lab/domain/flip.py`, lines 16 to 39:

```python
@dataclass(frozen=True, slots=True)
class FlipPlan:
    """The estimate on the deepest node, the node types in plan order, and the execution time."""

    estimate: int
    nodes: tuple[str, ...]
    milliseconds: float

    @property
    def scans_everything(self) -> bool:
        return "Seq Scan" in self.nodes

    @property
    def walks_the_index(self) -> bool:
        return "Index Scan Backward" in self.nodes


def parse_flip_plan(lines: Sequence[str]) -> FlipPlan:
    """Read a plan from `EXPLAIN (ANALYZE, BUFFERS)` text."""
    text = "\n".join(lines)
    estimates, execution = _ESTIMATE.findall(text), _EXECUTION.search(text)
    if not estimates or execution is None:
        raise PlanParseError("the plan has no row estimate or no Execution Time: was it produced with ANALYZE?")
    return FlipPlan(int(estimates[-1]), tuple(dict.fromkeys(_NODE.findall(text))), float(execution.group(1)))
```

`FlipPlan.scans_everything` is true if there is a `Seq Scan` node; `walks_the_index` is true for `Index Scan Backward`. The unit tests (`test_locks_backfill_flip.py`) feed it text like the above.

## Try it yourself

(After `make up db`.)

1. `cat sql/explain/f1_stale_statistics.txt` — the plan above.
2. Replay the three moments yourself (statistics note, items 2 to 4) and compare each `EXPLAIN` output with the committed file.
3. `docker compose exec db psql -U lab -d lab -c "explain select id, created_at from events where region = 'pacific' and city = 'seattle' order by created_at desc limit 100"` — only the estimate, no execution.
4. `.venv/bin/python -c "from locks_lab.domain.flip import parse_flip_plan as p; print(p(open('sql/explain/f2_after_analyze.txt').read().splitlines()))"` prints `FlipPlan(estimate=34127, nodes=('Index Scan Backward',), milliseconds=1.065)` (the committed numbers).

## Mistakes people make

- Running `EXPLAIN ANALYZE` on an `UPDATE` or `DELETE` in production without a transaction.
- Trusting one run: the first run may be slow because the cache is cold. Run twice and read the second.
- Comparing milliseconds across machines; compare ratios and page counts.
- Ignoring the estimate-versus-actual gap.
- Reading only the top line.
- Forgetting that `EXPLAIN` without `ANALYZE` does not show whether the index really helps.

**How this repository avoids them.** Plans are committed beside their query; the estimate and the actual rows are read from the same plan; and a test asserts the estimates, not only the speed.

## Check yourself

1. What is the difference between `EXPLAIN` and `EXPLAIN ANALYZE`? *The first shows the estimated plan without running the statement; the second runs it and adds actual times and row counts.*
2. What does `Rows Removed by Filter: 997252` tell you? *The scan read about a million rows and discarded almost all of them: wasted work an index could avoid.*
3. What do `shared hit=2058 read=61692` mean? *2,058 pages were found in PostgreSQL's cache and 61,692 were not, so they were fetched from outside it.*
4. Why prefer page counts to milliseconds when comparing two plans? *Page counts do not depend on how busy or fast the machine is.*
5. What does `SERIALIZE` add? *The cost of turning the result rows into the text sent to the client, including detoasting.*

## Further reading

- PostgreSQL 18, "Using EXPLAIN": https://www.postgresql.org/docs/18/using-explain.html
- `EXPLAIN` command reference (options): https://www.postgresql.org/docs/18/sql-explain.html

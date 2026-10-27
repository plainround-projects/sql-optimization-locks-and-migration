# PostgreSQL locks

## What it is

A **lock** is a claim a statement makes on a database object so that other statements cannot change it in a conflicting way while it is being used. Every statement takes locks automatically. Most are invisible because they are held for microseconds and do not conflict. They matter when a statement needs a *strong* lock on a table that others are using: it must wait, and the wait can hold up everything else.

## Why this repository uses it

Locks are the lesson. The question "how do I change a table that is in constant use?" is answered by knowing which statement takes which lock, how long it waits to get it and how long it holds it. The lab shows the lock queue as it forms, measures the damage of the naive statements, and measures the safe ones.

## Where it appears

| File | Role |
|---|---|
| `sql/naive/*.sql` | The three naive statements, each with a strong lock for a long time. |
| `sql/migrations/*.sql` | The safe versions, with `SET LOCAL lock_timeout`. |
| `sql/003_queries.sql` | The inspection queries on `pg_stat_activity` and `pg_locks`. |
| `src/locks_lab/infrastructure/lock_experiments.py` | The long read, the naive `ALTER`, the safe `ALTER`, and the snapshot of the lock queue. |
| `src/locks_lab/infrastructure/schema_changes.py` | Retry on `LockNotAvailable`; the lock modes of each step. |
| `src/locks_lab/domain/locks.py` | `WaitingSession`, `LockRequest`, `LockSnapshot`, `LockReport`. |
| `sql/explain/lock_queue.txt`, `results.md` | The evidence. |
| `docker-compose.yml` | `log_lock_waits=on`, `deadlock_timeout=1s`. |

## How it works underneath

**Table-level lock modes.** Eight modes, from weak to strong. Each mode lists which other modes it conflicts with; two sessions can hold the same table at the same time only if their modes do not conflict.

| Mode | Taken by | Conflicts with |
|---|---|---|
| `ACCESS SHARE` | `SELECT` (any read) | only `ACCESS EXCLUSIVE` |
| `ROW SHARE` | `SELECT ... FOR UPDATE` | `EXCLUSIVE`, `ACCESS EXCLUSIVE` |
| `ROW EXCLUSIVE` | `INSERT`, `UPDATE`, `DELETE` | `SHARE` and stronger |
| `SHARE UPDATE EXCLUSIVE` | `VACUUM`, `ANALYZE`, `CREATE INDEX CONCURRENTLY`, `CREATE STATISTICS`, `VALIDATE CONSTRAINT` | itself and stronger (not `ROW EXCLUSIVE`) |
| `SHARE` | plain `CREATE INDEX` | `ROW EXCLUSIVE` and stronger (so writes wait, reads do not) |
| `SHARE ROW EXCLUSIVE`, `EXCLUSIVE` | rare | most modes |
| `ACCESS EXCLUSIVE` | most `ALTER TABLE`, `DROP`, `TRUNCATE`, `VACUUM FULL` | **every mode, including reads** |

(`pg_locks` spells them `AccessShareLock`, `RowExclusiveLock`, ... `AccessExclusiveLock`.)

**Held until the end of the transaction.** A lock is released when the transaction commits or rolls back, not when the statement ends. A session that ran one `SELECT` inside `BEGIN` and then did nothing still holds its `ACCESS SHARE` lock: an "idle in transaction" session.

**The lock queue.** When a statement asks for a lock that conflicts with one held by someone else, it **waits**. The waiting requests form a **queue**. A *new* request that conflicts with a request already waiting must also wait *behind* it, even if it would not conflict with the locks currently held. This is the key fact of the lesson: an `ALTER TABLE` (needing `ACCESS EXCLUSIVE`) that waits behind a long-running read makes every later query on the table wait behind the `ALTER`, though those queries only wanted `ACCESS SHARE` or `ROW EXCLUSIVE`, which do not conflict with the read. One slow transaction plus one schema change stops the table.

**`lock_timeout`.** `SET lock_timeout = '2s'` (per session) or `SET LOCAL lock_timeout = '2s'` (inside a transaction, until it ends) makes a statement that has waited that long for a lock give up with an error (SQLSTATE `55P03`, "canceling statement due to lock timeout") instead of waiting forever. The client can then retry. A failed attempt still stood in the queue while it waited, so the timeout is also the longest stall a retry can cause. `statement_timeout` is different: it limits the total time of a statement, not the wait for a lock.

**Looking at locks.**

- `pg_locks`: one row per lock held or awaited: `pid` (the server process), `locktype` (`relation` for a table), `relation` (which table), `mode`, `granted` (`true` for held, `false` for waiting).
- `pg_stat_activity`: one row per session: `pid`, `application_name`, `query`, `state`, `wait_event_type` (`Lock` when waiting for a lock), `query_start`.
- `pg_blocking_pids(pid)`: the sessions that block the given one.
- `log_lock_waits = on` writes a server log line when a session has waited longer than `deadlock_timeout`.

**Deadlock.** Two sessions each waiting for a lock the other holds. PostgreSQL detects it after `deadlock_timeout` (1 s) and cancels one of them with an error.

## Walkthrough of this repository's use

### Step 2: the pile-up behind a naive ALTER

`sql/naive/01_add_column_behind_a_long_transaction.sql`, lines 1 to 3:

```sql
-- The naive migration of step 2: no lock_timeout. Run it in session B while session A holds
-- `BEGIN; SELECT * FROM events WHERE id = 1;` open. The ALTER waits for A, and everything after it waits for the ALTER.
ALTER TABLE events ADD COLUMN IF NOT EXISTS flagged boolean;
```

Three sessions are involved, each with its own `application_name`: **A** `long-transaction` runs `BEGIN; SELECT * FROM events WHERE id = 1;` and does nothing else, so it holds an `ACCESS SHARE` lock on `events`. **B** `naive-alter` runs the `ALTER TABLE ... ADD COLUMN` with no `lock_timeout`; adding a column needs `ACCESS EXCLUSIVE`, which conflicts with A's read, so B waits. **The load** (4 sessions) keeps running `INSERT`/`UPDATE`/`SELECT`; their `ROW EXCLUSIVE` and `ACCESS SHARE` requests do not conflict with A's lock, but they conflict with B's waiting `ACCESS EXCLUSIVE` request, so they queue behind B. The snapshot taken mid-pile-up (`sql/explain/lock_queue.txt`):

`sql/explain/lock_queue.txt`, lines 1 to 16:

```text
pg_stat_activity, sessions waiting on a lock (oldest first):
    pid application        blocked by     waiting s  query
   6318 naive-alter        [6317]               3.0  ALTER TABLE events ADD COLUMN flagged boolean
   4101 load               [6318]              -0.1  UPDATE events SET payload = payload || '{"seen": true}' WHERE id = $1
   4102 load               [6318]              -0.1  UPDATE events SET payload = payload || '{"seen": true}' WHERE id = $1
   4098 load               [6318]              -0.1  UPDATE events SET payload = payload || '{"seen": true}' WHERE id = $1
   4100 load               [6318]              -0.1  UPDATE events SET payload = payload || '{"seen": true}' WHERE id = $1

pg_locks on events (granted first, then the queue):
    pid application        mode                     granted
   6317 long-transaction   AccessShareLock          True
   6318 naive-alter        AccessExclusiveLock      False
   4101 load               RowExclusiveLock         False
   4102 load               RowExclusiveLock         False
   4098 load               RowExclusiveLock         False
   4100 load               RowExclusiveLock         False
```

Reading it: the first table (from `pg_stat_activity`) lists the sessions waiting on a lock, oldest first. `naive-alter` (pid 6318) is **blocked by [6317]**, which is `long-transaction` (second table, line `6317 long-transaction AccessShareLock True`: it holds its lock, `granted` is `True`). Every `load` session is **blocked by [6318]**, the ALTER, not by 6317, and in the second table their `RowExclusiveLock` requests are `granted False`: they never conflicted with the read, they wait for the ALTER's queued request. The negative `waiting s` of the load sessions (`-0.1`) is a quirk of the query: it computes `now() - query_start`, and `now()` is the time the *observer's* statement began, which was a moment before those statements started waiting. Result in `results.md`: ops per second fall from about 120 to 2.4, four stalled seconds, p99 of 3,031 ms and 8 errors (the load's 3-second statement timeout).

`src/locks_lab/domain/locks.py`, lines 29 to 61:

```python
@dataclass(frozen=True, slots=True)
class LockSnapshot:
    """The lock queue at one moment."""

    waiting: tuple[WaitingSession, ...]
    queue: tuple[LockRequest, ...]

    def waiting_application(self, application: str) -> tuple[WaitingSession, ...]:
        """The waiting sessions that belong to the named application."""
        return tuple(session for session in self.waiting if session.application == application)

    def request_of(self, pid: int) -> LockRequest | None:
        """The table lock the session holds or waits for."""
        return next((request for request in self.queue if request.pid == pid), None)

    def format(self) -> str:
        """The two views as text, the way the lesson's notes show them."""
        lines = [
            "pg_stat_activity, sessions waiting on a lock (oldest first):",
            f"{'pid':>7} {'application':18} {'blocked by':14} {'waiting s':>9}  query",
        ]
        lines += [
            f"{s.pid:>7} {s.application:18} {list(s.blocked_by)!s:14} {s.waiting_seconds:>9}  {s.query}"
            for s in self.waiting
        ]
        lines += [
            "",
            "pg_locks on events (granted first, then the queue):",
            f"{'pid':>7} {'application':18} {'mode':24} granted",
        ]
        lines += [f"{r.pid:>7} {r.application:18} {r.mode:24} {r.granted}" for r in self.queue]
        return "\n".join(lines) + "\n"

```

`LockSnapshot.format()` builds exactly that text from the two views.

### Step 3: the safe ALTER gives up

`sql/migrations/001_add_flagged_column.sql`, lines 1 to 8:

```sql
-- Step 3, expand: a nullable column and a default for new rows. Both are metadata-only (no table rewrite),
-- and the lock_timeout makes the statement give up instead of queueing behind a long transaction.
-- Safe to run twice. Undo: down/001_add_flagged_column.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE events ADD COLUMN IF NOT EXISTS flagged boolean;
ALTER TABLE events ALTER COLUMN flagged SET DEFAULT false;
COMMIT;
```

`SET LOCAL lock_timeout = '2s'` (inside the transaction, so it ends with it) makes the ALTER give up after two seconds of waiting. The two statements are metadata-only: `ADD COLUMN IF NOT EXISTS flagged boolean` (a nullable column with no default needs no table rewrite) and `ALTER COLUMN flagged SET DEFAULT false` (applies to future rows). When the lock cannot be had, PostgreSQL raises error `55P03`; the Python code catches it and retries after a pause (psycopg note). The forced-conflict experiment shows it: with the long read open and `lock_timeout = '1s'`, the ALTER failed after 1.00 s (`results.md`, "Forced conflict ... failed fast: True"). It still held up the load for that second, because the failed attempt was in the queue while it waited: "the timeout is also the longest stall a retry can cause".

### Step 4: which lock does an index build take?

`sql/naive/02_create_index_blocking_writes.sql`, lines 1 to 3:

```sql
-- The naive index build of step 4: a plain CREATE INDEX holds a SHARE lock for the whole build, so inserts,
-- updates and deletes on events wait until it finishes. Reads still run.
CREATE INDEX IF NOT EXISTS idx_events_naive ON events (device_id, created_at DESC);
```

A plain `CREATE INDEX` takes a `SHARE` lock for the whole build: reads continue (`ACCESS SHARE` does not conflict) but inserts, updates and deletes (`ROW EXCLUSIVE`) wait. In `results.md`: build 3.2 s, p99 3,003 ms, slowest operation 3,011 ms, 4 errors. `CREATE INDEX CONCURRENTLY` (migration `003`) takes `SHARE UPDATE EXCLUSIVE`, which does not conflict with `ROW EXCLUSIVE`, so writes continue (0 errors, slowest operation 491 ms on a loaded machine). The price: two table scans, a longer build and the invalid-index leftover (PostgreSQL online schema changes note).

### Step 5: NOT NULL and the lock of each move

`sql/naive/03_set_not_null_scanning_the_table.sql`, lines 1 to 5:

```sql
-- The naive NOT NULL of step 5, on a scratch column: SET NOT NULL with no validated CHECK scans every row
-- while holding ACCESS EXCLUSIVE, so every query on events waits for the scan.
ALTER TABLE events ADD COLUMN IF NOT EXISTS scratch boolean DEFAULT false;
ALTER TABLE events ALTER COLUMN scratch SET NOT NULL;
ALTER TABLE events DROP COLUMN IF EXISTS scratch;
```

A `SET NOT NULL` with no proof must scan every row to make sure none is NULL, **while holding `ACCESS EXCLUSIVE`** for the whole scan: in `results.md` the naive version held it for 1,783 ms and the load stalled. The three-move version reports, from `pg_locks` inside each move's own transaction:

`src/locks_lab/infrastructure/schema_changes.py`, lines 181 to 214:

```python
    def _report(self, statements: Iterable[str], lock_timeout: str = "2s") -> LockReport:
        """Run statements in one transaction; report the lock modes it held on events, how long it took, and tries."""

        def attempt(connection: psycopg.Connection[Any]) -> LockReport:
            connection.execute("BEGIN")
            try:
                started = time.perf_counter()
                for statement in statements:
                    connection.execute(statement)
                seconds = time.perf_counter() - started
                modes = tuple(
                    row[0]
                    for row in connection.execute(
                        "SELECT mode FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'relation' "
                        "AND relation = 'events'::regclass ORDER BY mode"
                    )
                )
                connection.execute("COMMIT")
                return LockReport(seconds, modes)
            except psycopg.Error:
                connection.execute("ROLLBACK")
                raise

        with session(self._settings, application_name="migration") as connection:
            connection.execute(f"SET lock_timeout = '{lock_timeout}'")
            tries = 0

            def counted() -> LockReport:
                nonlocal tries
                tries += 1
                return attempt(connection)

            report = retry(counted, attempts=LOCK_RETRIES, base_delay_seconds=1.0, retry_on=(errors.LockNotAvailable,))
        return LockReport(report.seconds, report.lock_modes, tries)
```

and the table in `results.md`: move 1 (`ADD CONSTRAINT ... CHECK (flagged IS NOT NULL) NOT VALID`) `AccessExclusiveLock` for 2.6 ms; move 2 (`VALIDATE CONSTRAINT`) `ShareUpdateExclusiveLock` for 462 ms (the scan, with reads *and writes* flowing); move 3 (`SET NOT NULL`, then `DROP CONSTRAINT`) `AccessExclusiveLock` for 5.6 ms. The strong lock is held only when no scan is needed.

### The lab's own politeness

`src/locks_lab/infrastructure/lab_table.py`, lines 30 to 49:

```python
    def reset(self) -> None:
        """Remove what the lab added: column, indexes, constraint, statistics, and every row beyond the seed.

        DDL runs under a lock_timeout and is retried, so a reset never joins a lock queue for good.
        """
        with session(self._settings, application_name="lab-reset") as connection:
            connection.execute("SET lock_timeout = '5s'")
            for statement in _RESET_STATEMENTS:
                try:
                    retry(
                        lambda: connection.execute(statement),  # noqa: B023  (called inside this iteration)
                        attempts=10,
                        base_delay_seconds=1.0,
                        retry_on=(errors.LockNotAvailable,),
                    )
                except errors.LockNotAvailable as error:
                    raise LockWaitTimeoutError(f"could not get the lock to reset the lab: {statement}") from error
            connection.execute("DELETE FROM events WHERE id > (SELECT value FROM lab_meta WHERE key = 'seed_max_id')")
            connection.execute("ALTER TABLE events RESET (autovacuum_enabled)")
            connection.execute("VACUUM (ANALYZE) events")
```

Even the reset follows the rule: `SET lock_timeout = '5s'` and a retry on `LockNotAvailable` for every DDL statement.

## Try it yourself

(After `make up db`; use two terminals.)

1. Terminal 1: `make psql`, then `begin; select * from events where id = 1;` — leave the transaction open.
2. Terminal 2: `docker compose exec db psql -U lab -d lab -c "alter table events add column probe boolean"` — it hangs (the naive ALTER). Do not close it yet.
3. Terminal 3: `docker compose exec db psql -U lab -d lab -c "select pid, pg_blocking_pids(pid), left(query, 50) from pg_stat_activity where wait_event_type = 'Lock'"` — shows the ALTER waiting, blocked by the pid of terminal 1. Also run `select pid, mode, granted from pg_locks where relation = 'events'::regclass` — `AccessShareLock t` and `AccessExclusiveLock f`.
4. Terminal 1: `rollback;` — terminal 2's ALTER completes at once. Clean up with `docker compose exec db psql -U lab -d lab -c "alter table events drop column probe"` (or `make reset db`).
5. Repeat with `-c "set lock_timeout = '1s'; alter table events add column probe boolean"` in terminal 2: it fails after 1 second with `ERROR:  canceling statement due to lock timeout`.
6. `make run` produces `sql/explain/lock_queue.txt` for your machine.

## Mistakes people make

- Running `ALTER TABLE` on a busy table without a `lock_timeout`.
- Leaving a transaction open (a forgotten `BEGIN`, a session paused in a debugger, an application that holds a transaction while calling a slow service).
- Believing "it only takes a millisecond", forgetting the time spent *waiting* for the lock.
- Retrying in a tight loop with no pause.
- Mixing up `lock_timeout` and `statement_timeout`.

**How this repository avoids them.** Every migration that needs a strong lock sets `SET LOCAL lock_timeout`, and the application retries with a pause; waits are logged by the server (`log_lock_waits`); the strong lock of the `NOT NULL` change is held only when no scan is needed; and the reset script obeys the same rules.

## Check yourself

1. Which table lock does a plain `SELECT` take, and what is its only conflict? *`ACCESS SHARE`; it conflicts only with `ACCESS EXCLUSIVE`.*
2. Why can an `ALTER TABLE` waiting behind a read block other readers? *Later requests queue behind the waiting `ACCESS EXCLUSIVE` request, which conflicts with all of them.*
3. What does `lock_timeout` do? *Makes a statement give up after waiting that long for a lock, with error `55P03`.*
4. When is a lock released? *At the end of the transaction.*
5. How do you see who blocks whom? *`pg_stat_activity` with `pg_blocking_pids(pid)`, and `pg_locks` (`granted = false` rows).*

## Further reading

- PostgreSQL 18, "Explicit Locking": https://www.postgresql.org/docs/18/explicit-locking.html
- `pg_locks`: https://www.postgresql.org/docs/18/view-pg-locks.html ; `pg_stat_activity`: https://www.postgresql.org/docs/18/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW
- Client connection defaults (`lock_timeout`): https://www.postgresql.org/docs/18/runtime-config-client.html

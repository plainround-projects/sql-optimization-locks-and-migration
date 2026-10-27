# Python threads

## What it is

A **thread** is an independent line of execution inside one running program. A program normally does one thing at a time; with threads it can wait for one thing while doing another: send statements to a database over four connections at once, or watch a clock once a second while others work. All the threads of a program share its memory. The standard module `threading` creates and manages them.

## Why this repository uses it

The lesson is about a table under constant load while it is being changed, so something has to be sending inserts, updates and reads *at the same time as* the experiments run. The load script runs on background threads. The experiments also need a second actor: a naive `ALTER TABLE` that waits for a lock while the main thread watches the lock views, and a `CREATE INDEX CONCURRENTLY` that another thread cancels at the right moment.

## Where it appears

| File | Threads |
|---|---|
| `infrastructure/load_runner.py` | `ThreadedLoad`: four worker threads and one reporter thread, a stop `Event`, a `Lock`. |
| `infrastructure/lock_experiments.py` | One thread runs the naive `ALTER` while the main thread samples the lock views. |
| `infrastructure/schema_changes.py` | One thread builds an index while the main thread cancels the build. |
| `interfaces/load_cli.py`, `run_cli.py` | Use `ThreadedLoad` as a context manager. |
| `tests/integration/test_lesson_outcomes.py` | `threading.Timer` releases a lock after 3 seconds. |
| `pyproject.toml` | `locks_lab.domain` and `locks_lab.application` may not import `threading` (import-linter). |

## How it works underneath

**Creating and running.** `t = threading.Thread(target=function, args=(1,), name="load-1", daemon=True)` prepares a thread; `t.start()` starts it, and then `function(1)` runs at the same time as the code that called `start()`. `t.join(timeout=5)` waits up to 5 seconds for it to finish. `t.is_alive()` tells whether it is still running. A **daemon** thread does not keep the program alive: when the main thread ends, daemon threads are stopped abruptly.

**Taking turns.** CPython (the standard Python) runs Python code in only one thread at a time, switching between them (the *global interpreter lock*). So threads do not make CPU-heavy Python faster. They are the right tool when threads mostly **wait** — for the network, for a database, for `time.sleep` — because a waiting thread lets the others run. This repository's threads spend nearly all their time waiting for PostgreSQL.

**Sharing data safely.** Two threads that change the same list or counter at the same moment can corrupt it or produce wrong results. Tools:

- `threading.Lock()`: only one thread at a time can hold it. `with lock:` takes it for the block and always releases it. The load keeps one lock around its shared lists.
- `threading.Event()`: a thread-safe flag. `.set()` raises it, `.clear()` lowers it, `.is_set()` reads it, and `.wait(seconds)` sleeps until the flag is set **or** the time has passed (returning whether it was set). It is the standard way to say "stop" to threads.
- Immutable values and appending to a list are used with care: single operations such as `list.append` or `dict.pop` are safe in CPython, but a sequence of operations is not.

**Timing and pacing.** `time.monotonic()` is a clock that never goes backwards, suited to measuring intervals and deadlines. `event.wait(timeout)` is better than `time.sleep` for a worker that must also react to "stop".

**Stopping threads cleanly.** Python cannot kill a thread. The pattern is: the owner sets an Event, each thread checks it between units of work and returns, and the owner calls `join`.

**`threading.Timer(seconds, function)`** runs a function once after a delay on its own thread; `.start()` starts it and `.cancel()` cancels it.

**`threading.get_ident()`** returns a number identifying the current thread.

## Walkthrough of this repository's use

### The load: start, stop, shared state

`src/locks_lab/infrastructure/load_runner.py`, lines 28 to 81:

```python
logger = logging.getLogger(__name__)
_EVENT_TYPES = ["click", "view", "error", "purchase", "login"]


class ThreadedLoad:
    """Runs the load on background threads from `start()` until `stop()`; also usable as a context manager."""

    def __init__(
        self,
        postgres: PostgresSettings,
        load: LoadSettings,
        *,
        metrics_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._postgres = postgres
        self._load = load
        self._metrics_path = metrics_path
        self._clock = clock
        self._samples: list[Sample] = []
        self._ticks: list[Tick] = []
        self._inflight: dict[int, float] = {}
        self._recent_ids: collections.deque[int] = collections.deque(maxlen=5000)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------------------------------------------
    def start(self) -> ThreadedLoad:
        """Start the workers and the reporter."""
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._work, args=(index,), name=f"load-{index}", daemon=True)
            for index in range(self._load.workers)
        ]
        self._threads.append(threading.Thread(target=self._report, name="load-reporter", daemon=True))
        for thread in self._threads:
            thread.start()
        return self

    def stop(self) -> None:
        """Ask the threads to finish what they are doing and wait for them; connections are closed by the workers."""
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=self._load.statement_timeout_ms / 1000 + 5)

    def __enter__(self) -> ThreadedLoad:
        return self.start()

    def __exit__(
        self, _kind: type[BaseException] | None, _error: BaseException | None, _traceback: TracebackType | None
    ) -> None:
        self.stop()

```

- `_EVENT_TYPES` is a module constant: the five kinds of event the load inserts.
- `ThreadedLoad.__init__` stores the settings and creates the shared state: `self._samples` (a list of finished statements), `self._ticks` (one summary per second), `self._inflight` (a dictionary from thread id to the time its current statement started), `self._recent_ids` (a `deque` of the last inserted ids), `self._stop = threading.Event()` (the stop flag), `self._threads` (the thread objects) and `self._lock = threading.Lock()` (guards the two lists). `clock: Callable[[], float] = time.monotonic` is the time source; tests can replace it.
- `start()` clears the stop flag and creates the threads in a list comprehension: `threading.Thread(target=self._work, args=(index,), name=f"load-{index}", daemon=True)` for each of the `workers` (4), plus one `load-reporter` thread running `self._report`. `daemon=True` means the threads cannot keep the program alive if it is interrupted. Then each thread is started and `self` is returned (so `ThreadedLoad(...).start()` can be chained).
- `stop()` sets the event and `join`s every thread, waiting up to the statement timeout plus 5 seconds: a worker may be in the middle of a statement and must be allowed to finish it and close its connection.
- `__enter__` and `__exit__` make the class a **context manager**: `with ThreadedLoad(...) as load:` starts the load on entry and stops it on exit, whatever happens in the block. `__exit__` receives the error information (unused here, hence the leading underscores) and returns `None`, so errors are not swallowed.

### The port methods

`src/locks_lab/infrastructure/load_runner.py`, lines 82 to 99:

```python
    # -- the port --------------------------------------------------------------------------------------------
    def now(self) -> float:
        return self._clock()

    def mark(self, label: str) -> None:
        """Write a label into the per-second record (the metrics file, when there is one)."""
        self._append_metrics({"t": round(self._clock(), 2), "mark": label})

    def summary(self, start: float, end: float) -> WindowSummary:
        with self._lock:
            samples, ticks = list(self._samples), list(self._ticks)
        return summarize(samples, ticks, start, end)

    def measure(self, seconds: float) -> WindowSummary:
        start = self.now()
        time.sleep(seconds)
        return self.summary(start, self.now())

```

`now()` is the load's clock. `mark(label)` writes a labelled line into the per-second file. `summary(start, end)` copies the shared lists inside `with self._lock:` (a quick copy, so the lock is held for a moment only) and calls the pure function `summarize` from the domain outside the lock. `measure(seconds)` lets the load run: `time.sleep(seconds)` in the calling thread while the workers keep working, then it summarizes that stretch.

### The three statements

`src/locks_lab/infrastructure/load_runner.py`, lines 100 to 122:

```python
    # -- the three statements ---------------------------------------------------------------------------------
    def _insert(self, connection: psycopg.Connection[Any]) -> None:
        row = connection.execute(
            "INSERT INTO events (device_id, event_type, region, city, payload) "
            "VALUES (%s, %s, 'north', 'amber', '{\"v\": 1}') RETURNING id",
            (random.randint(1, 100000), random.choice(_EVENT_TYPES)),
        ).fetchone()
        if row:
            self._recent_ids.append(row[0])

    def _update(self, connection: psycopg.Connection[Any]) -> None:
        if self._recent_ids:
            connection.execute(
                "UPDATE events SET payload = payload || '{\"seen\": true}' WHERE id = %s",
                (random.choice(self._recent_ids),),
            )

    def _read(self, connection: psycopg.Connection[Any]) -> None:
        connection.execute(
            "SELECT id, event_type, created_at FROM events "
            "WHERE created_at >= now() - interval '1 minute' ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

```

Each is one SQL statement through psycopg (psycopg note): `_insert` adds a row with a random device and a random event type and keeps the new id (`RETURNING id`, then `self._recent_ids.append(row[0])`); `_update` picks a recent id from the deque and appends `{"seen": true}` to its `payload` (JSONB concatenation with `||`); `_read` asks for the 20 newest events of the last minute (`created_at >= now() - interval '1 minute' ORDER BY created_at DESC LIMIT 20`). Values go in as parameters (`%s`), never pasted into the text.

### A worker

`src/locks_lab/infrastructure/load_runner.py`, lines 123 to 163:

```python
    # -- workers and reporter -----------------------------------------------------------------------------------
    def _work(self, index: int) -> None:
        interval = self._load.workers / self._load.iterations_per_second
        due = self._clock() + index * interval / self._load.workers
        connection: psycopg.Connection[Any] | None = None
        while not self._stop.is_set():
            self._stop.wait(max(0.0, due - self._clock()))
            due = max(due + interval, self._clock())  # after a stall, resume the pace instead of catching up
            for name, operation in (("insert", self._insert), ("update", self._update), ("read", self._read)):
                if self._stop.is_set():
                    break
                connection = self._timed(connection, name, operation)
        if connection is not None and not connection.closed:
            connection.close()

    def _timed(
        self,
        connection: psycopg.Connection[Any] | None,
        name: str,
        operation: Callable[[psycopg.Connection[Any]], None],
    ) -> psycopg.Connection[Any] | None:
        identity = threading.get_ident()
        started = self._clock()
        ok = True
        try:
            if connection is None or connection.closed:
                connection = connect(
                    self._postgres, application_name="load", statement_timeout_ms=self._load.statement_timeout_ms
                )
            self._inflight[identity] = started
            operation(connection)
        except psycopg.Error:
            ok = False
            if connection is not None and (connection.closed or connection.broken):
                connection = None
        finally:
            self._inflight.pop(identity, None)
            finished = self._clock()
            with self._lock:
                self._samples.append(Sample(finished, name, (finished - started) * 1000, ok))
        return connection
```

- `interval = self._load.workers / self._load.iterations_per_second`: each of the 4 workers must start an iteration every 4/40 = 0.1 seconds, so together they do 40 iterations a second (each iteration is an insert, an update and a read: 120 operations a second).
- `due = self._clock() + index * interval / self._load.workers` staggers the workers so they do not all fire at once.
- The loop `while not self._stop.is_set():` runs until the stop flag is raised. `self._stop.wait(max(0.0, due - self._clock()))` **sleeps until the next due time but wakes at once if the flag is set**: this is why the load stops promptly. `due = max(due + interval, self._clock())` schedules the next iteration; the comment says why `max`: after a stall, resume the pace instead of catching up (a catch-up burst would hide the stall).
- `for name, operation in (("insert", self._insert), ("update", self._update), ("read", self._read)):` runs the three operations, each through `_timed`, and breaks out early if stopping.
- After the loop the worker closes its own connection (`connection.close()`), so connections are closed by the thread that opened them.

`src/locks_lab/infrastructure/load_runner.py`, lines 138 to 163:

```python
    def _timed(
        self,
        connection: psycopg.Connection[Any] | None,
        name: str,
        operation: Callable[[psycopg.Connection[Any]], None],
    ) -> psycopg.Connection[Any] | None:
        identity = threading.get_ident()
        started = self._clock()
        ok = True
        try:
            if connection is None or connection.closed:
                connection = connect(
                    self._postgres, application_name="load", statement_timeout_ms=self._load.statement_timeout_ms
                )
            self._inflight[identity] = started
            operation(connection)
        except psycopg.Error:
            ok = False
            if connection is not None and (connection.closed or connection.broken):
                connection = None
        finally:
            self._inflight.pop(identity, None)
            finished = self._clock()
            with self._lock:
                self._samples.append(Sample(finished, name, (finished - started) * 1000, ok))
        return connection
```

`_timed(connection, name, operation)` runs one operation and records how it went:

- `identity = threading.get_ident()`: this thread's number, the key in the `_inflight` dictionary.
- `started = self._clock()`; if the worker has no open connection, it opens one with `application_name="load"` (so the lock views can tell the load's sessions apart) and the load's own statement timeout (3 seconds).
- `self._inflight[identity] = started` marks "this thread is waiting since `started`"; `operation(connection)` runs the statement.
- `except psycopg.Error:` marks the sample as failed (`ok = False`; a statement that waited 3 seconds for a lock fails with a timeout) and drops the connection if it is closed or broken, so the next iteration opens a new one.
- `finally:` always runs: it removes the thread from `_inflight`, takes the finish time and appends a `Sample` under the lock. The method returns the connection to reuse (or `None`).

### The reporter

`src/locks_lab/infrastructure/load_runner.py`, lines 165 to 188:

```python
    def _report(self) -> None:
        window_start = self._clock()
        while not self._stop.wait(1.0):
            now = self._clock()
            ages = [(now - started) * 1000 for started in list(self._inflight.values())]
            with self._lock:
                tick = make_tick(now, window_start, self._samples, ages)
                self._ticks.append(tick)
            window_start = now
            logger.debug("load tick", extra=fields(ops=tick.ops, errors=tick.errors, p99_ms=round(tick.p99_ms, 2)))
            self._append_metrics(
                {
                    "t": round(tick.t, 2),
                    "ops": tick.ops,
                    "errors": tick.errors,
                    "p99_ms": round(tick.p99_ms, 2),
                    "oldest_inflight_ms": round(tick.oldest_inflight_ms, 1),
                }
            )

    def _append_metrics(self, entry: dict[str, object]) -> None:
        if self._metrics_path:
            with self._metrics_path.open("a") as handle:
                handle.write(json.dumps(entry) + "\n")
```

The reporter thread wakes once a second: `while not self._stop.wait(1.0):` waits one second or until the stop flag is set (when it returns `True` the loop ends). Each second it computes the **ages of operations still waiting** (`[(now - started) * 1000 for started in list(self._inflight.values())]`, a copy of the dictionary's values), builds a `Tick` with the pure function `make_tick` under the lock, appends it, logs it at debug level and writes a JSON line to `load-metrics.jsonl`. This is what makes a stall visible: during a lock pile-up no operation *finishes*, but the ages of the waiting ones grow, so the tick's p99 and `oldest_inflight_ms` rise. `_append_metrics` is explained in the standard-library note.

### Threads in the experiments

`src/locks_lab/infrastructure/lock_experiments.py`, lines 64 to 88:

```python
    def lock_queue(self, hold_seconds: float) -> QueueOutcome:
        """Open the read, start the naive ALTER behind it, sample the views mid-pile-up, then release the read."""
        observer = connect(self._settings, application_name="lab-observer")
        long_transaction = self._long_read()
        outcome: dict[str, float] = {}

        def naive_alter() -> None:
            with connect(self._settings, application_name="naive-alter") as alter_connection:
                started = time.perf_counter()
                alter_connection.execute("ALTER TABLE events ADD COLUMN flagged boolean")
                outcome["alter_seconds"] = time.perf_counter() - started

        alter_thread = threading.Thread(target=naive_alter, name="naive-alter")
        alter_thread.start()
        try:
            time.sleep(hold_seconds / 2)
            snapshot = snapshot_locks(observer)  # the queue as it stands, mid-pile-up
            time.sleep(hold_seconds / 2)
        finally:
            long_transaction.rollback()
            long_transaction.close()
            alter_thread.join()
            observer.close()
        logger.info("lock queue observed", extra=fields(waiting=len(snapshot.waiting), held_seconds=hold_seconds))
        return QueueOutcome(snapshot, outcome["alter_seconds"])
```

`lock_queue(hold_seconds)` sets the scene for the lesson's second step. It opens an observer connection, then `_long_read()`: a connection with `autocommit=False` that runs a `SELECT` and is left open, so it holds a lock on the table (`AccessShareLock`) until it rolls back. The naive `ALTER` is defined as an inner function `naive_alter` and runs on its own thread, `threading.Thread(target=naive_alter, name="naive-alter")`, because the `ALTER` will **block** (it needs a lock that the long read prevents) and the main thread must stay free to look at the lock views. After `hold_seconds / 2` the main thread takes a snapshot of who waits for whom; after another half, the `finally` block rolls back the long read (the `ALTER` can now proceed), closes it, `join`s the ALTER thread and closes the observer. The inner function writes its result into a dictionary (`outcome["alter_seconds"]`) because a thread's function cannot return a value to the caller.

`src/locks_lab/infrastructure/schema_changes.py`, lines 123 to 162:

```python
    def interrupted_concurrent_build(self, phase: str = "index validation", attempts: int = 5) -> InterruptedBuild:
        """Start CREATE INDEX CONCURRENTLY in another session and cancel it once it reaches `phase`.

        Cancelled in its validation phase the index is already marked ready (so every write maintains it) but never
        became valid (so no query can use it). That is the leftover the lesson wants found. The build is quick on a
        small table, so a cancel that arrives too late is cleaned up and tried again.
        """
        path = migration_file(self._sql_dir, 3)
        cancelled = False
        with session(self._settings, application_name="lab-observer") as observer:
            for _ in range(attempts):
                outcome: dict[str, bool] = {}

                def build(outcome: dict[str, bool] = outcome) -> None:
                    with session(self._settings, application_name="index-build") as builder:
                        try:
                            run_file(builder, path)
                        except errors.QueryCanceled:
                            outcome["cancelled"] = True

                thread = threading.Thread(target=build, name="index-build")
                thread.start()
                while thread.is_alive():
                    row = observer.execute(
                        "SELECT pid FROM pg_stat_progress_create_index WHERE phase LIKE %s", (phase + "%",)
                    ).fetchone()
                    if row:
                        observer.execute("SELECT pg_cancel_backend(%s)", (row[0],))
                        break
                    time.sleep(0.01)
                thread.join()
                cancelled = outcome.get("cancelled", False)
                if cancelled:
                    break
                observer.execute(f"DROP INDEX IF EXISTS {DEVICE_INDEX}")  # finished before the cancel: try again
            state = observer.execute(
                f"SELECT indisvalid, indisready FROM pg_index WHERE indexrelid = to_regclass('{DEVICE_INDEX}')"
            ).fetchone()
        ready_but_invalid = state is not None and bool(state[1]) and not state[0]
        return InterruptedBuild(cancelled, tuple(self.invalid_indexes()), ready_but_invalid)
```

`interrupted_concurrent_build` starts `CREATE INDEX CONCURRENTLY` on a thread (`build`) and, from the main thread, polls `pg_stat_progress_create_index` every 10 ms (`time.sleep(0.01)`) until the build reaches the phase called "index validation", then cancels that backend with `pg_cancel_backend`. Details a beginner could miss: `def build(outcome: dict[str, bool] = outcome) -> None:` binds the current `outcome` dictionary as a **default argument**, which fixes its value when the function is defined, so each retry's thread writes into its own dictionary; `thread.is_alive()` is the loop condition; `thread.join()` waits for the build thread to end; and if the build finished before the cancel arrived, the index is dropped and the attempt repeated (up to 5 times).

### In a test

`tests/integration/test_lesson_outcomes.py`, lines 80 to 92:

```python
def test_step3_a_failed_attempt_retries_instead_of_giving_up(changes, settings):
    from locks_lab.infrastructure.postgres import connect

    long_read = connect(settings.postgres, autocommit=False, application_name="long-transaction")
    long_read.execute("SELECT * FROM events WHERE id = 1").fetchall()
    release = threading.Timer(3.0, long_read.rollback)  # after the first attempt's 2 s lock_timeout
    release.start()
    try:
        attempts = changes.apply(1)
    finally:
        release.join()
        long_read.close()
    assert attempts >= 2, "the first try hit lock_timeout; a retry after the read ended succeeded"
```

`threading.Timer(3.0, long_read.rollback)` runs `long_read.rollback()` once, 3 seconds from now, on its own thread; the main thread meanwhile starts a migration whose first attempt will give up after its 2-second lock timeout and whose second attempt, after the read is released, succeeds. `release.join()` waits for the timer thread.

## Try it yourself

1. A thread and an Event, with no database:

   ```bash
   .venv/bin/python - <<'EOF'
   import threading, time
   stop = threading.Event()
   def worker():
       n = 0
       while not stop.wait(0.2):      # wakes every 0.2 s, or at once when stop is set
           n += 1
       print("worker saw", n, "ticks")
   t = threading.Thread(target=worker, name="demo")
   t.start()
   time.sleep(1.0)
   stop.set()
   t.join()
   print("alive after join:", t.is_alive())
   EOF
   ```

   It prints `worker saw 4 ticks` (or 5; timing varies by a tick) and `alive after join: False`.
2. A lock protecting a shared counter:

   ```bash
   .venv/bin/python - <<'EOF'
   import threading
   n = 0
   lock = threading.Lock()
   def add():
       global n
       for _ in range(100_000):
           with lock:
               n += 1
   threads = [threading.Thread(target=add) for _ in range(4)]
   for t in threads: t.start()
   for t in threads: t.join()
   print(n)
   EOF
   ```

   It prints `400000`: four threads each added 100,000 times, one at a time inside the lock. (`global n` lets the function change the module-level variable.)
3. With the database up (`make up db`): `make load SECONDS=10` starts the load. You see one line per second like `ops= 120 errors=  0 p99=     3.1 ms` and, at the end, a JSON summary of the window.
4. In a second terminal, while `make load SECONDS=30` runs, open `make psql` and run `select application_name, count(*) from pg_stat_activity where datname = 'lab' group by 1` — you see `load` with 4 connections (the four worker threads' connections).
5. `tail -3 load-metrics.jsonl` after `make run` shows lines such as `{"t": 123.45, "ops": 118, "errors": 0, "p99_ms": 4.2, "oldest_inflight_ms": 3.1}` and `{"t": ..., "mark": "step 2: a long read, then a naive ALTER behind it"}`.

## Mistakes people make

- Expecting threads to speed up CPU-bound Python.
- Sharing a list or dict between threads without a lock, and reading half-updated data.
- Forgetting `join`, so the program ends while work is unfinished (or, for non-daemon threads, never ends).
- Using `time.sleep` in a worker that should stop promptly (use `Event.wait`).
- Letting an exception kill a thread silently; catch and record errors inside the thread function.
- Holding a lock while waiting for something slow.

**How this repository avoids them.** Shared lists are guarded by one lock and copied before the pure statistics run. Threads are stopped with an Event and joined; the worker that opened a connection closes it. Waiting uses `Event.wait`, so stopping is prompt. The domain and application contain no threads (import-linter), so the logic that matters is tested without any timing.

## Check yourself

1. Why do threads help a program that talks to a database? *While one thread waits for the database, others can run.*
2. What does `Event.wait(1.0)` do? *Sleeps until the event is set or one second has passed, whichever comes first.*
3. What does `with lock:` guarantee? *Only one thread at a time runs the block, and the lock is released afterwards even on an error.*
4. How do you stop a thread? *Set an Event it checks between units of work, then `join` it; threads cannot be killed from outside.*
5. What is a daemon thread? *A thread that does not keep the program alive: it is stopped when the main thread ends.*

## Further reading

- `threading` module (3.13): https://docs.python.org/3.13/library/threading.html
- Thread-safe objects and the GIL: https://docs.python.org/3.13/glossary.html#term-global-interpreter-lock

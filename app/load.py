"""The lesson's load script: steady inserts, updates on recent rows and reads, with p99 and error rate every second.

Each iteration does one insert, one update of a row inserted a few moments ago, and one read of recent events,
paced to a steady rate. A second's p99 counts the operations that finished in it and the age of any operation
still waiting, so a stall shows up as a high p99 even when nothing completes (otherwise a full outage would
look like silence).
"""
import argparse
import collections
import json
import math
import random
import threading
import time

import psycopg

from app import db

STALL_MS = 500          # an operation older than this at a one-second tick counts the second as stalled


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


class LoadRunner:
    def __init__(self, iterations_per_second=40, workers=4, statement_timeout_ms=3000, verbose=False, metrics_path=None):
        self.iterations_per_second = iterations_per_second
        self.workers = workers
        self.statement_timeout_ms = statement_timeout_ms
        self.verbose = verbose
        self.metrics_path = metrics_path
        self.samples = []                                   # (finished_at, operation, milliseconds, ok)
        self.timeline = []                                  # one dict per second
        self._inflight = {}
        self._recent_ids = collections.deque(maxlen=5000)
        self._stop = threading.Event()
        self._threads = []
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------------------------------------------
    def start(self):
        self._stop.clear()
        self._threads = [threading.Thread(target=self._work, args=(index,), daemon=True) for index in range(self.workers)]
        self._threads.append(threading.Thread(target=self._report, daemon=True))
        for thread in self._threads:
            thread.start()
        return self

    def stop(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=self.statement_timeout_ms / 1000 + 5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc_info):
        self.stop()

    # -- the three operations ----------------------------------------------------------------------------------
    def _insert(self, connection):
        row = connection.execute(
            "INSERT INTO events (device_id, event_type, region, city, payload) "
            "VALUES (%s, %s, 'north', 'amber', '{\"v\": 1}') RETURNING id",
            (random.randint(1, 100000), random.choice(["click", "view", "error", "purchase", "login"]))).fetchone()
        self._recent_ids.append(row[0])

    def _update(self, connection):
        if self._recent_ids:
            connection.execute("UPDATE events SET payload = payload || '{\"seen\": true}' WHERE id = %s",
                               (random.choice(self._recent_ids),))

    def _read(self, connection):
        connection.execute("SELECT id, event_type, created_at FROM events "
                           "WHERE created_at >= now() - interval '1 minute' ORDER BY created_at DESC LIMIT 20").fetchall()

    # -- workers and reporter ----------------------------------------------------------------------------------
    def _work(self, index):
        interval = self.workers / self.iterations_per_second
        due = time.monotonic() + index * interval / self.workers
        connection = None
        while not self._stop.is_set():
            self._stop.wait(max(0.0, due - time.monotonic()))
            due = max(due + interval, time.monotonic())      # after a stall, resume the pace instead of catching up
            for name, operation in (("insert", self._insert), ("update", self._update), ("read", self._read)):
                if self._stop.is_set():
                    break
                connection, _ = self._timed(connection, name, operation)
        if connection is not None and not connection.closed:
            connection.close()

    def _timed(self, connection, name, operation):
        identity = threading.get_ident()
        started = time.monotonic()
        ok = True
        try:
            if connection is None or connection.closed:
                connection = db.connect(application_name="load", statement_timeout=self.statement_timeout_ms)
            self._inflight[identity] = started
            operation(connection)
        except psycopg.Error:
            ok = False
            if connection is not None and (connection.closed or connection.broken):
                connection = None
        finally:
            self._inflight.pop(identity, None)
            finished = time.monotonic()
            with self._lock:
                self.samples.append((finished, name, (finished - started) * 1000, ok))
        return connection, ok

    def _report(self):
        window_start = time.monotonic()
        while not self._stop.wait(1.0):
            now = time.monotonic()
            with self._lock:
                finished = [sample for sample in self.samples if window_start <= sample[0] < now]
            ages = [(now - started) * 1000 for started in list(self._inflight.values())]
            latencies = [sample[2] for sample in finished] + ages
            entry = {"t": round(now, 2), "ops": len(finished), "errors": sum(not sample[3] for sample in finished),
                     "p99_ms": round(percentile(latencies, 0.99), 2), "oldest_inflight_ms": round(max(ages, default=0), 1)}
            self.timeline.append(entry)
            window_start = now
            if self.verbose:
                print(f"ops={entry['ops']:4d} errors={entry['errors']:3d} p99={entry['p99_ms']:8.1f} ms "
                      f"oldest_waiting={entry['oldest_inflight_ms']:7.1f} ms", flush=True)
            if self.metrics_path:
                with open(self.metrics_path, "a") as handle:
                    handle.write(json.dumps(entry) + "\n")

    # -- measurements ------------------------------------------------------------------------------------------
    def now(self):
        return time.monotonic()

    def mark(self, label):
        """Put a label in the per-second record, so a spike can be matched to the step that caused it."""
        entry = {"t": round(time.monotonic(), 2), "mark": label}
        self.timeline.append(entry)
        if self.metrics_path:
            with open(self.metrics_path, "a") as handle:
                handle.write(json.dumps(entry) + "\n")

    def summary(self, start, end):
        """Operations that finished in [start, end): counts, p99 over them, and how many seconds stalled."""
        with self._lock:
            window = [sample for sample in self.samples if start <= sample[0] < end]
        ticks = [entry for entry in self.timeline if "p99_ms" in entry and start <= entry["t"] - 0.5 < end]
        latencies = [sample[2] for sample in window]
        seconds = max(end - start, 1e-9)
        return {
            "seconds": round(seconds, 1), "ops": len(window), "ops_per_second": round(len(window) / seconds, 1),
            "errors": sum(not sample[3] for sample in window),
            "p50_ms": round(percentile(latencies, 0.50), 2), "p99_ms": round(percentile(latencies, 0.99), 2),
            "max_ms": round(max(latencies, default=0), 1),
            "worst_second_p99_ms": max((entry["p99_ms"] for entry in ticks), default=0),
            "stalled_seconds": sum(entry["oldest_inflight_ms"] >= STALL_MS for entry in ticks),
        }

    def measure(self, seconds):
        """Let the load run for `seconds` and summarize that stretch."""
        start = self.now()
        time.sleep(seconds)
        return self.summary(start, self.now())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--rate", type=int, default=40, help="iterations per second (three operations each)")
    arguments = parser.parse_args()
    with LoadRunner(arguments.rate, verbose=True) as runner:
        start = runner.now()
        time.sleep(arguments.seconds)
        print(json.dumps(runner.summary(start, runner.now()), indent=2))


if __name__ == "__main__":
    main()

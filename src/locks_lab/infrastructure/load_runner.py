"""Adapter: the lesson's load script. Implements `LoadGenerator`.

Steady inserts, updates on recently inserted rows and reads of recent events, paced to a fixed rate over a few
connections, with a one-second reporter. Every statement has a timeout, so a lock pile-up shows as errors and
high latencies instead of a hung program.
"""

from __future__ import annotations

import collections
import json
import logging
import random
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

import psycopg

from ..domain.stats import Sample, Tick, WindowSummary, make_tick, summarize
from .logging import fields
from .postgres import connect
from .settings import LoadSettings, PostgresSettings

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

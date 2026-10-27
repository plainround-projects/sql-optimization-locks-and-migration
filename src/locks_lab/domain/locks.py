"""What the lock views show, as values: who waits for whom, which requests are queued, which lock a step held."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WaitingSession:
    """A session waiting on a lock (pg_stat_activity), and the sessions it is blocked by."""

    pid: int
    application: str
    blocked_by: tuple[int, ...]
    waiting_seconds: float
    query: str


@dataclass(frozen=True, slots=True)
class LockRequest:
    """One lock on the table, granted or still queued (pg_locks)."""

    pid: int
    application: str
    mode: str
    granted: bool


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


@dataclass(frozen=True, slots=True)
class LockReport:
    """A statement run in its own transaction: how long it took, the lock modes it held, and the tries it needed."""

    seconds: float
    lock_modes: tuple[str, ...]
    attempts: int = 1

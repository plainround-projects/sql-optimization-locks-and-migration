"""Read the lock views: who waits, for whom, and which lock requests are queued on events."""
from psycopg.rows import dict_row

WAITING = """
SELECT pid, application_name, pg_blocking_pids(pid) AS blocked_by, wait_event_type, wait_event,
       left(query, 70) AS query, round(extract(epoch FROM now() - query_start)::numeric, 1) AS waiting_seconds
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid() AND wait_event_type = 'Lock'
ORDER BY query_start
"""
QUEUE = """
SELECT l.pid, a.application_name, l.mode, l.granted
FROM pg_locks l JOIN pg_stat_activity a USING (pid)
WHERE l.relation = 'events'::regclass AND l.locktype = 'relation'
ORDER BY l.granted DESC, a.query_start
"""


def snapshot(connection):
    cursor = connection.cursor(row_factory=dict_row)
    return {"waiting": cursor.execute(WAITING).fetchall(), "queue": cursor.execute(QUEUE).fetchall()}


def format_snapshot(state):
    lines = ["pg_stat_activity, sessions waiting on a lock (oldest first):",
             f"{'pid':>7} {'application':12} {'blocked by':14} {'waiting s':>9}  query"]
    lines += [f"{row['pid']:>7} {row['application_name']:12} {str(row['blocked_by']):14} {row['waiting_seconds']:>9}  {row['query']}"
              for row in state["waiting"]]
    lines += ["", "pg_locks on events (granted first, then the queue):",
              f"{'pid':>7} {'application':12} {'mode':24} granted"]
    lines += [f"{row['pid']:>7} {row['application_name']:12} {row['mode']:24} {row['granted']}" for row in state["queue"]]
    return "\n".join(lines) + "\n"

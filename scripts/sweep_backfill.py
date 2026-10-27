"""Find the backfill batch size that keeps the load's p99 inside the bar.

Each arm starts from the same state: a fresh database volume (make down, up, db), the column added, ten seconds of
baseline, then 25 seconds of backfill at the given batch size and pause. Fresh starts matter: the first pass over a
freshly loaded table is the expensive one, and a later arm on the same volume would look better than it is.
This DESTROYS the lab database and takes about six minutes. Output is also written to sql/explain/backfill-sweep.txt.
"""
import collections
import subprocess
import time

from app import db, migrate
from app.load import LoadRunner, percentile

ARMS = [(10000, 0.1), (2000, 0.05), (5000, 0.1), (10000, 0.1), (2000, 0.05), (5000, 0.1)]
SECONDS = 25


def fresh_database():
    for target in ("down", "up", "db"):
        subprocess.run(["make", target], cwd=db.ROOT, capture_output=True, check=True)


def run_arm(batch_size, pause):
    fresh_database()
    with db.connect() as connection:
        migrate.apply_with_retry(connection, db.migration(1))
        with LoadRunner() as runner:
            baseline = runner.measure(10)
            start, started, first_id = runner.now(), time.monotonic(), 1
            while time.monotonic() - started < SECONDS:
                migrate.apply_with_retry(connection, db.migration(2), params={"first_id": first_id, "last_id": first_id + batch_size - 1})
                first_id += batch_size
                time.sleep(pause)
            end = runner.now()
            window = runner.summary(start, end)
            by_operation = collections.defaultdict(list)
            for finished, name, milliseconds, _ in list(runner.samples):
                if start <= finished < end:
                    by_operation[name].append(milliseconds)
    return baseline["p99_ms"], window["p99_ms"], percentile(by_operation["insert"], 0.99), (first_id - 1) / SECONDS


def main():
    lines = [f"{SECONDS} s of backfill from a fresh database each time; load p99 in ms; rows/s is the backfill's speed",
             f"{'batch':>6} {'pause s':>8} {'baseline':>9} {'backfill':>9} {'ratio':>6} {'insert p99':>11} {'rows/s':>8}"]
    for batch_size, pause in ARMS:
        baseline, backfill, insert_p99, rate = run_arm(batch_size, pause)
        lines.append(f"{batch_size:>6} {pause:>8} {baseline:>9.2f} {backfill:>9.2f} {backfill / baseline:>5.1f}x {insert_p99:>11.1f} {rate:>8.0f}")
        print(lines[-1], flush=True)
    (db.EXPLAIN_DIR / "backfill-sweep.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

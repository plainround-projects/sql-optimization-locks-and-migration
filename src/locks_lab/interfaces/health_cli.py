"""Health command: exit 0 when PostgreSQL holds the seeded events table.

python -m locks_lab.interfaces.health_cli
"""

from __future__ import annotations

from collections.abc import Sequence

from ..application.health import check_health
from ..infrastructure.health_probes import PostgresEventsProbe
from .common import load_settings


def main(_argv: Sequence[str] | None = None) -> int:
    """Check PostgreSQL; returns 0 when healthy, 1 when not, 2 when the configuration is unusable."""
    settings = load_settings()
    if settings is None:
        return 2
    report = check_health([PostgresEventsProbe(settings.postgres)])
    for result in report.results:
        print(f"{'ok' if result.ok else 'FAIL'} {result.name}: {result.detail}")
    return 0 if report.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())

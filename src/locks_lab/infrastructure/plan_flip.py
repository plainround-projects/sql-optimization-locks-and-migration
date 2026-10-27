"""Adapter: the plan regression and its fix. Implements `PlanFlipLab`."""

from __future__ import annotations

from pathlib import Path

from ..domain.lesson import EXTENDED_STATISTICS, FLIP_PLANS
from ..domain.outcomes import FlipOutcome
from .postgres import scalar, session
from .settings import PostgresSettings
from .sql_script import run_file


class PostgresPlanFlip:
    """Loads a correlated month and plans the query three times: stale, after ANALYZE, after extended statistics."""

    def __init__(self, settings: PostgresSettings, sql_dir: Path) -> None:
        self._settings = settings
        self._sql_dir = sql_dir

    def run(self) -> FlipOutcome:
        plans: dict[str, tuple[str, ...]] = {}
        with session(self._settings, application_name="plan-flip") as connection:
            run_file(connection, self._sql_dir / "experiments" / "01_bulk_load_correlated_month.sql")
            actual = int(
                scalar(connection, "SELECT count(*) FROM events WHERE region = 'pacific' AND city = 'seattle'")
            )

            def capture(name: str) -> None:
                rows = run_file(connection, self._sql_dir / "explain" / f"{name}.sql")
                plans[name] = tuple(row[0] for row in rows)

            first, second, third = FLIP_PLANS
            capture(first)
            connection.execute("ANALYZE events")
            capture(second)
            connection.execute(
                f"CREATE STATISTICS {EXTENDED_STATISTICS} (dependencies, mcv) ON region, city FROM events"
            )
            connection.execute("ANALYZE events")
            capture(third)
        return FlipOutcome(actual, plans)

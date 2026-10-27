"""Replay the lesson with the load running throughout; writes results.md, the lock queue and the plans.

python -m locks_lab.interfaces.run_cli [--baseline-seconds N] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Sequence
from pathlib import Path

from ..application.replay import ReplayLesson
from ..domain.errors import LabError, LessonInterruptedError
from ..infrastructure.artifacts import FileArtifactStore
from ..infrastructure.load_runner import ThreadedLoad
from ..infrastructure.logging import fields
from ..infrastructure.shutdown import ShutdownSignal
from .common import build_scenarios, build_table, load_settings, measure_host_load

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the replay. Exit codes: 0 done, 1 lab error, 2 bad configuration, 130 interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-seconds", type=int, help="steady load before the first change (default BASELINE_SECONDS)"
    )
    parser.add_argument("--output-dir", type=Path, help="where the notes and plans go (default: sql/explain)")
    arguments = parser.parse_args(argv)
    settings = load_settings()
    if settings is None:
        return 2
    shutdown = ShutdownSignal()
    shutdown.install()
    baseline = arguments.baseline_seconds or settings.baseline_seconds
    metrics = Path("load-metrics.jsonl")
    try:
        with ThreadedLoad(settings.postgres, settings.load, metrics_path=metrics) as load:
            replay = ReplayLesson(
                load=load,
                table=build_table(settings),
                scenarios=build_scenarios(settings, time.sleep, lambda: shutdown.requested),
                store=FileArtifactStore(arguments.output_dir or settings.sql_dir / "explain"),
                baseline_seconds=baseline,
                closing_seconds=settings.closing_seconds,
                batch_size=settings.migration.batch_size,
                pause_seconds=settings.migration.pause_seconds,
                host_load=measure_host_load(),
                progress=lambda message: logger.info(message),
                should_stop=lambda: shutdown.requested,
            )
            result = replay.run()
    except LessonInterruptedError:
        logger.warning("interrupted; the table is left mid-lesson, the next run resets it first")
        return 130
    except LabError as error:
        logger.error("the lesson failed", extra=fields(error=error))
        return 1
    verdict = "within" if result.bar.allows(result.safe.summary) else "not within"
    safe_p99, baseline_p99 = result.safe.summary.p99_ms, result.bar.baseline_p99_ms
    print(f"safe migration p99 {safe_p99} ms: {verdict} twice the baseline ({baseline_p99} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The lesson's scenario through the command-line programs, as the Makefile runs them (make up db first)."""

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e

# A shared machine can take longer than the 5 s default to accept a connection while the replay runs.
SLOW_MACHINE = {"PG_CONNECT_TIMEOUT_SECONDS": os.environ.get("PG_CONNECT_TIMEOUT_SECONDS", "30")}


def program(module: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", f"locks_lab.interfaces.{module}", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **SLOW_MACHINE, **env},
        timeout=1800,
        check=False,
    )


def test_the_health_command_is_green_on_the_seeded_database():
    result = program("health_cli")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok postgres:" in result.stdout


def test_the_load_command_reports_a_steady_rate_as_json():
    result = program("load_cli", "--seconds", "4")
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout[result.stdout.index("{") :])
    assert summary["errors"] == 0
    assert summary["ops_per_second"] > 80


def test_the_replay_writes_the_notes_the_lock_queue_and_the_three_plans(tmp_path):
    result = program(
        "run_cli", "--baseline-seconds", "8", "--output-dir", str(tmp_path), CLOSING_SECONDS="8", LOG_LEVEL="WARNING"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    notes = (tmp_path / "results.md").read_text()
    assert "| 1 baseline, opening |" in notes
    assert "## Step 6: the plan flip" in notes
    assert "naive-alter" in (tmp_path / "lock_queue.txt").read_text()
    assert "Seq Scan on events" in (tmp_path / "f1_stale_statistics.txt").read_text()
    assert "Index Scan Backward" in (tmp_path / "f3_after_extended_statistics.txt").read_text()
    assert "safe migration p99" in result.stdout

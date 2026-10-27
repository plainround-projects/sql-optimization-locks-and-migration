import pytest

from locks_lab.application.health import ProbeFailedError
from locks_lab.domain.errors import LabError
from locks_lab.interfaces import health_cli, load_cli, run_cli


def test_a_missing_password_is_a_configuration_error_with_exit_code_2_for_every_program(monkeypatch, capsys):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    assert health_cli.main([]) == 2
    assert run_cli.main([]) == 2
    assert load_cli.main([]) == 2
    assert "PGPASSWORD" in capsys.readouterr().err


class FailingProbe:
    name = "postgres"

    def __init__(self, _settings) -> None:
        pass

    def check(self) -> str:
        raise ProbeFailedError("the events table is empty or not seeded; run make db")


class PassingProbe(FailingProbe):
    def check(self) -> str:
        return "2,000,000 events"


def test_health_is_exit_1_when_the_probe_fails(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setattr(health_cli, "PostgresEventsProbe", FailingProbe)
    assert health_cli.main([]) == 1
    assert "FAIL postgres: the events table is empty" in capsys.readouterr().out


def test_health_is_exit_0_when_the_probe_passes(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setattr(health_cli, "PostgresEventsProbe", PassingProbe)
    assert health_cli.main([]) == 0
    assert "ok postgres: 2,000,000 events" in capsys.readouterr().out


class FakeReplay:
    """Stands in for ReplayLesson: returns what the test says, or raises what it says."""

    outcome: object = None

    def __init__(self, **_options) -> None:
        pass

    def run(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeLoadContext:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


def patch_run(monkeypatch, outcome):
    monkeypatch.setenv("PGPASSWORD", "x")
    FakeReplay.outcome = outcome
    monkeypatch.setattr(run_cli, "ReplayLesson", FakeReplay)
    monkeypatch.setattr(run_cli, "ThreadedLoad", FakeLoadContext)
    monkeypatch.setattr(run_cli, "build_table", lambda _settings: None)
    monkeypatch.setattr(run_cli, "build_scenarios", lambda *_args: None)


def test_an_interrupted_replay_exits_with_130(monkeypatch, tmp_path):
    from locks_lab.domain.errors import LessonInterruptedError

    patch_run(monkeypatch, LessonInterruptedError("stopped"))
    assert run_cli.main(["--output-dir", str(tmp_path)]) == 130


def test_a_lab_error_exits_with_1(monkeypatch, tmp_path):
    patch_run(monkeypatch, LabError("boom"))
    assert run_cli.main(["--output-dir", str(tmp_path)]) == 1


def test_a_finished_replay_prints_whether_the_safe_migration_met_the_bar(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    from locks_lab.domain.stats import Bar

    from ..application.fakes import window

    outcome = SimpleNamespace(bar=Bar(10.0), safe=SimpleNamespace(summary=window(12.0)))
    patch_run(monkeypatch, outcome)
    assert run_cli.main(["--output-dir", str(tmp_path), "--baseline-seconds", "5"]) == 0
    assert "safe migration p99 12.0 ms: within twice the baseline (10.0 ms)" in capsys.readouterr().out


def test_a_bad_argument_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        run_cli.main(["--baseline-seconds", "x"])

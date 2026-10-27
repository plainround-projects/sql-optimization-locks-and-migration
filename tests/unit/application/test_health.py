from locks_lab.application.health import ProbeFailedError, check_health


class Probe:
    def __init__(self, name: str, error: str | None = None) -> None:
        self.name, self._error = name, error

    def check(self) -> str:
        if self._error:
            raise ProbeFailedError(self._error)
        return "fine"


def test_all_probes_passing_is_healthy():
    report = check_health([Probe("a"), Probe("b")])
    assert report.healthy
    assert [r.detail for r in report.results] == ["fine", "fine"]


def test_one_failing_probe_is_reported_and_makes_the_report_unhealthy():
    report = check_health([Probe("a"), Probe("b", "down")])
    assert not report.healthy
    assert [(r.name, r.ok, r.detail) for r in report.results] == [("a", True, "fine"), ("b", False, "down")]

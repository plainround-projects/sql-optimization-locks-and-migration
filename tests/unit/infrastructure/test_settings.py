import pytest

from locks_lab.infrastructure.settings import ConfigurationError, Settings

MINIMAL = {"PGPASSWORD": "s3cret-value"}


def test_defaults_describe_the_local_compose_setup():
    settings = Settings.from_env(MINIMAL)
    postgres = settings.postgres
    assert (postgres.host, postgres.port, postgres.database, postgres.user) == ("localhost", 55433, "lab", "lab")
    assert (settings.load.iterations_per_second, settings.load.workers, settings.load.statement_timeout_ms) == (
        40,
        4,
        3000,
    )
    assert (settings.migration.batch_size, settings.migration.pause_seconds, settings.migration.lock_timeout) == (
        2000,
        0.05,
        "2s",
    )
    assert (settings.baseline_seconds, settings.closing_seconds, settings.log_level) == (60, 20, "INFO")
    assert settings.sql_dir.name == "sql"


def test_the_database_password_has_no_default():
    with pytest.raises(ConfigurationError, match="PGPASSWORD"):
        Settings.from_env({})


def test_the_password_never_appears_in_a_printed_settings_object():
    assert "s3cret-value" not in repr(Settings.from_env(MINIMAL))


def test_every_variable_can_be_overridden():
    settings = Settings.from_env(
        {
            **MINIMAL,
            "PGHOST": "db",
            "PGPORT": "6543",
            "PGDATABASE": "x",
            "PGUSER": "u",
            "LOAD_ITERATIONS_PER_SECOND": "10",
            "LOAD_WORKERS": "2",
            "LOAD_STATEMENT_TIMEOUT_MS": "500",
            "BACKFILL_BATCH": "10000",
            "BACKFILL_PAUSE_SECONDS": "0.1",
            "LOCK_TIMEOUT": "500ms",
            "BASELINE_SECONDS": "600",
            "CLOSING_SECONDS": "30",
            "LAB_SQL_DIR": "/somewhere/sql",
            "LOG_LEVEL": "debug",
        }
    )
    assert (settings.postgres.host, settings.postgres.port) == ("db", 6543)
    assert (settings.load.iterations_per_second, settings.load.workers) == (10, 2)
    assert (settings.migration.batch_size, settings.migration.pause_seconds) == (10000, 0.1)
    assert settings.migration.lock_timeout == "500ms"
    assert (settings.baseline_seconds, settings.closing_seconds) == (600, 30)
    assert (settings.log_level, str(settings.sql_dir)) == ("DEBUG", "/somewhere/sql")


@pytest.mark.parametrize(
    "extra",
    [
        {"PGPORT": "0"},
        {"PGHOST": "  "},
        {"LOAD_WORKERS": "0"},
        {"BACKFILL_BATCH": "many"},
        {"BACKFILL_PAUSE_SECONDS": "-1"},
        {"BACKFILL_PAUSE_SECONDS": "soon"},
        {"LOCK_TIMEOUT": "2 seconds"},
        {"LOG_LEVEL": "LOUD"},
    ],
)
def test_an_unusable_value_is_rejected_with_the_variable_name(extra):
    with pytest.raises(ConfigurationError, match=next(iter(extra))):
        Settings.from_env({**MINIMAL, **extra})


def test_settings_read_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "from-the-process")
    assert Settings.from_env().postgres.password == "from-the-process"

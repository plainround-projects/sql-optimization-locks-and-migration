import pytest

from app import db, scenarios
from app.load import LoadRunner


@pytest.fixture(scope="session")
def connection():
    with db.connect() as live_connection:
        yield live_connection


@pytest.fixture
def lab(connection):
    """The baseline table before the test, and again after it (the load is stopped first, see `runner`)."""
    scenarios.reset_lab(connection)
    yield connection
    scenarios.reset_lab(connection)


@pytest.fixture
def runner(lab):
    """The load script, running for the whole test."""
    with LoadRunner() as running:
        yield running

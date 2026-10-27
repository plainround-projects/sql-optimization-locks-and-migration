"""Connections from the PG* variables the Makefile exports."""
import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
MIGRATIONS = sorted((SQL_DIR / "migrations").glob("*.sql"))
EXPLAIN_DIR = SQL_DIR / "explain"


def connect(autocommit=True, application_name="migration", **settings):
    """A connection with session settings (for example statement_timeout=3000).

    Parallel query is off so plans read the same on the compose database and on a CI service container.
    """
    settings = {"max_parallel_workers_per_gather": 0, **settings}
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "55433"),
        user=os.environ.get("PGUSER", "lab"),
        password=os.environ.get("PGPASSWORD", "lab"),
        dbname=os.environ.get("PGDATABASE", "lab"),
        application_name=application_name,
        options=" ".join(f"-c {name}={value}" for name, value in settings.items()),
        autocommit=autocommit,
    )


def split_statements(sql_text):
    """Split SQL on semicolons, ignoring comments and quoted text (enough for the files in sql/)."""
    without_comments = "\n".join(line.split("--", 1)[0] for line in sql_text.splitlines())
    statements, current, quote = [], [], None
    for character in without_comments:
        if quote:
            quote = None if character == quote else quote
        elif character in ("'", '"'):
            quote = character
        elif character == ";":
            statements.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    return [statement for statement in statements if statement]


def run_file(connection, path, params=None):
    """Run every statement of a file on one connection; return the rows of the last one that returns rows."""
    text = Path(path).read_text()
    if params:                                        # the files use psql's :name; psycopg wants %(name)s
        for name in params:
            text = text.replace(f":{name}", f"%({name})s")
    rows = []
    for statement in split_statements(text):
        cursor = connection.execute(statement, params) if params and "%(" in statement else connection.execute(statement)
        if cursor.description:
            rows = cursor.fetchall()
    return rows


def migration(number):
    """The migration file whose name starts with the given number, for example migration(3)."""
    return next(path for path in MIGRATIONS if path.name.startswith(f"{number:03d}_"))

import pathlib

from locks_lab.infrastructure.sql_script import split_statements


def test_statements_are_split_on_semicolons():
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_comments_are_dropped_even_with_a_semicolon_in_them():
    assert split_statements("-- one; two\nSELECT 1; -- trailing; note\nSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_a_semicolon_inside_quotes_does_not_split():
    assert split_statements("SELECT 'a;b'; SELECT \"c;d\";") == ["SELECT 'a;b'", 'SELECT "c;d"']


def test_a_do_block_is_one_statement_whatever_it_contains():
    sql = "DO $$\nBEGIN\n  IF true THEN SELECT 1; END IF;\nEND\n$$;\nSELECT 2;"
    statements = split_statements(sql)
    assert len(statements) == 2
    assert statements[0].startswith("DO $$")
    assert statements[0].endswith("$$")


def test_a_tagged_dollar_quote_is_one_statement():
    assert split_statements("SELECT $q$a;b$q$; SELECT 2;") == ["SELECT $q$a;b$q$", "SELECT 2"]


def test_psql_meta_commands_are_not_sql():
    assert split_statements("\\set rows 5\nSELECT 1;\n\\gset\n") == ["SELECT 1"]


def test_every_repository_sql_file_that_python_runs_splits_into_complete_statements():
    sql = pathlib.Path(__file__).resolve().parents[3] / "sql"
    files = [*sorted((sql / "migrations").rglob("*.sql")), *sorted((sql / "explain").glob("*.sql"))]
    files += [sql / "experiments" / "01_bulk_load_correlated_month.sql"]
    for path in files:
        statements = split_statements(path.read_text())
        assert statements, path.name
        assert all(not statement.endswith(";") for statement in statements)

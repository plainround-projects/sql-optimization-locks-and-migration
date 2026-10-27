# Technology notes

This folder teaches every technology used in this repository, from zero, through the repository's own files. The repository changes a busy `events` table (a column, an index, a `NOT NULL`) while a load script keeps running, and causes and fixes a plan regression. You do not need to know any of the technologies in advance: each note defines its terms, explains how the technology works underneath, walks through the lines of *this* repository that use it, gives commands to try, lists common mistakes and ends with five questions.

Every note has the same nine parts: what it is, why this repository uses it, where it appears, how it works underneath, a walkthrough of this repository's use, try it yourself, mistakes people make (and how this repository avoids them), check yourself, and further reading.

Commands in the notes are run from the repository root. Where a note shows output, it was produced by running the command in this repository; numbers that depend on the machine (milliseconds, process ids, load averages) will differ on yours.

## If you have ten minutes

1. [postgresql-locks](postgresql-locks.md): the lock queue is the lesson.
1. [postgresql-online-schema-changes](postgresql-online-schema-changes.md): the safe way to make each change.
1. [python-threads](python-threads.md): how the load and the experiments run together.

## The notes, in the order to read them

Read the language first, then the build and packaging tools, then the runtime pieces, then the database, then the tests and checks.

| # | Note | What it covers |
|---:|---|---|
| 1 | [bash](bash.md) | Bash and the shell: the shell commands in the Makefile, the CI file, the Dockerfile and the compose health check |
| 2 | [python](python.md) | Python: the language, and a walk through the domain, application and start-up code |
| 3 | [python-typing](python-typing.md) | Type hints: protocols (ports), generics, `TYPE_CHECKING` |
| 4 | [python-dataclasses](python-dataclasses.md) | Dataclasses: the frozen value objects used across the layers |
| 5 | [python-standard-library](python-standard-library.md) | The standard library modules the code uses (files, retries, SQL file runner...) |
| 6 | [regular-expressions](regular-expressions.md) | Regular expressions that read plans and validate settings |
| 7 | [python-threads](python-threads.md) | Threads, events and locks |
| 8 | [logging](logging.md) | Logging and the logfmt line format |
| 9 | [command-line-programs](command-line-programs.md) | Command-line programs: arguments, exit codes, signals, graceful shutdown |
| 10 | [dotenv-and-environment-variables](dotenv-and-environment-variables.md) | Environment variables, `.env` and the settings validation |
| 11 | [json](json.md) | JSON (and JSON Lines) where the code reads or writes it |
| 12 | [toml](toml.md) | TOML and `pyproject.toml`: project metadata and the settings of every tool |
| 13 | [setuptools](setuptools.md) | setuptools and packaging: how `src/` becomes an installable package with commands |
| 14 | [pip-and-venv](pip-and-venv.md) | pip, virtual environments and the hashed lock files |
| 15 | [uv](uv.md) | uv: the tool that produced the lock files |
| 16 | [make](make.md) | Make: the `Makefile` targets `up`, `db`, `run`, `test`, `lint`, `down` and the rest |
| 17 | [docker](docker.md) | Docker: the `Dockerfile`, `.dockerignore`, images and containers |
| 18 | [docker-compose](docker-compose.md) | Docker Compose: `docker-compose.yml`, which starts PostgreSQL 18 |
| 19 | [yaml](yaml.md) | YAML: the format of the compose file and the CI workflow |
| 20 | [sql](sql.md) | SQL: every statement of the repository's `.sql` files |
| 21 | [psql](psql.md) | psql: the command-line client and its meta-commands |
| 22 | [postgresql](postgresql.md) | PostgreSQL: pages, MVCC, WAL, vacuum, settings, system views |
| 23 | [postgresql-indexes](postgresql-indexes.md) | PostgreSQL indexes used by the lab |
| 24 | [postgresql-locks](postgresql-locks.md) | PostgreSQL locks, the lock queue and `lock_timeout` |
| 25 | [postgresql-online-schema-changes](postgresql-online-schema-changes.md) | Changing a table while it is in use: expand and contract, backfill, concurrent index, NOT NULL in three moves |
| 26 | [postgresql-statistics](postgresql-statistics.md) | Planner statistics, `ANALYZE`, extended statistics and the plan flip |
| 27 | [explain-query-plans](explain-query-plans.md) | `EXPLAIN` and how to read a plan |
| 28 | [psycopg](psycopg.md) | psycopg 3: the PostgreSQL driver |
| 29 | [pytest](pytest.md) | pytest: unit, integration and end-to-end tests |
| 30 | [coverage](coverage.md) | Coverage: coverage.py and pytest-cov |
| 31 | [ruff](ruff.md) | ruff: linting and formatting |
| 32 | [mypy](mypy.md) | mypy: the strict type checker |
| 33 | [import-linter](import-linter.md) | import-linter: the dependency rule between the layers |
| 34 | [pip-audit](pip-audit.md) | pip-audit: the vulnerability check of the locked dependencies |
| 35 | [github-actions](github-actions.md) | GitHub Actions: `.github/workflows/ci.yml`, the checks run on every push |
| 36 | [git](git.md) | Git and `.gitignore` |
| 37 | [editorconfig](editorconfig.md) | EditorConfig: the editor rules of the repository |
| 38 | [markdown-and-mermaid](markdown-and-mermaid.md) | Markdown and Mermaid: the documentation files and diagrams |

## Which note explains which source file

| Source | Note |
|---|---|
| `Makefile` | [make](make.md), [bash](bash.md) |
| `Dockerfile`, `.dockerignore` | [docker](docker.md), [bash](bash.md) |
| `docker-compose.yml` | [docker-compose](docker-compose.md), [yaml](yaml.md) |
| `.github/workflows/ci.yml` | [github-actions](github-actions.md), [yaml](yaml.md) |
| `pyproject.toml` | [toml](toml.md), [setuptools](setuptools.md), [ruff](ruff.md), [mypy](mypy.md), [pytest](pytest.md), [coverage](coverage.md), [import-linter](import-linter.md) |
| `requirements.lock`, `requirements-dev.lock` | [pip-and-venv](pip-and-venv.md), [uv](uv.md), [pip-audit](pip-audit.md) |
| `.gitignore` | [git](git.md) |
| `.editorconfig` | [editorconfig](editorconfig.md) |
| `.env.example` and `.env` | [dotenv-and-environment-variables](dotenv-and-environment-variables.md) |
| `README.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `docs/adr/*.md` | [markdown-and-mermaid](markdown-and-mermaid.md) |
| `sql/*.sql`, `sql/migrations/` | [sql](sql.md), [psql](psql.md), [postgresql](postgresql.md) |
| `sql/explain/` | [explain-query-plans](explain-query-plans.md) |
| `sql/migrations/*.sql`, `sql/naive/*.sql` | [postgresql-online-schema-changes](postgresql-online-schema-changes.md), [postgresql-locks](postgresql-locks.md), [postgresql-indexes](postgresql-indexes.md) |
| `sql/experiments/*.sql` | [postgresql-statistics](postgresql-statistics.md) |
| `src/locks_lab/domain/*.py` | [python](python.md), [python-dataclasses](python-dataclasses.md), [python-typing](python-typing.md), [regular-expressions](regular-expressions.md) |
| `src/locks_lab/application/*.py` | [python](python.md), [python-typing](python-typing.md), [python-dataclasses](python-dataclasses.md) |
| `src/locks_lab/infrastructure/load_runner.py` | [python-threads](python-threads.md), [psycopg](psycopg.md), [json](json.md) |
| `src/locks_lab/infrastructure/lock_experiments.py` | [python-threads](python-threads.md), [postgresql-locks](postgresql-locks.md), [psycopg](psycopg.md) |
| `src/locks_lab/infrastructure/schema_changes.py` | [postgresql-online-schema-changes](postgresql-online-schema-changes.md), [postgresql-locks](postgresql-locks.md), [psycopg](psycopg.md), [python-threads](python-threads.md) |
| `src/locks_lab/infrastructure/plan_flip.py`, `lab_table.py` | [postgresql-statistics](postgresql-statistics.md), [psycopg](psycopg.md) |
| `src/locks_lab/infrastructure/postgres.py`, `health_probes.py` | [psycopg](psycopg.md) |
| `src/locks_lab/infrastructure/settings.py` | [dotenv-and-environment-variables](dotenv-and-environment-variables.md), [python-dataclasses](python-dataclasses.md), [regular-expressions](regular-expressions.md) |
| `src/locks_lab/infrastructure/logging.py` | [logging](logging.md) |
| `src/locks_lab/infrastructure/retry.py`, `artifacts.py`, `sql_script.py` | [python-standard-library](python-standard-library.md) |
| `src/locks_lab/infrastructure/shutdown.py`, `interfaces/*.py` | [command-line-programs](command-line-programs.md) |
| `tests/` | [pytest](pytest.md), [coverage](coverage.md) |

## Dependencies you do not see in the code

The lock file pins more packages than the code imports: the *dependencies of the dependencies*. This table is read from `requirements-dev.lock` (`# via` comments): each package, the version, who needs it, and the note that explains the package that needs it.

| Package | Version | Needed by | Explained in |
|---|---|---|---|
| `ast-serialize` | 0.13.1 | `mypy` | [mypy](mypy.md) |
| `boolean-py` | 5.0 | `license-expression` | [pip-audit](pip-audit.md) |
| `cachecontrol` | 0.14.4 | `pip-audit` | [pip-audit](pip-audit.md) |
| `certifi` | 2026.10.23 | `requests` |  |
| `charset-normalizer` | 3.5.2 | `requests` |  |
| `click` | 8.5.0 | `import-linter` | [import-linter](import-linter.md) |
| `colorama` | 0.4.6 | `pytest` | [pytest](pytest.md) |
| `coverage` | 7.17.0 | `pytest-cov` | [coverage](coverage.md) |
| `cyclonedx-python-lib` | 11.12.0 | `pip-audit` | [pip-audit](pip-audit.md) |
| `defusedxml` | 0.7.1 | `py-serializable` | [pip-audit](pip-audit.md) |
| `filelock` | 4.2.4 | `cachecontrol` | [pip-audit](pip-audit.md) |
| `grimp` | 3.18 | `import-linter` | [import-linter](import-linter.md) |
| `idna` | 3.20 | `requests` |  |
| `iniconfig` | 2.3.1 | `pytest` | [pytest](pytest.md) |
| `librt` | 0.16.0 | `mypy` | [mypy](mypy.md) |
| `license-expression` | 30.4.4 | `cyclonedx-python-lib` | [pip-audit](pip-audit.md) |
| `markdown-it-py` | 4.2.0 | `rich` | [import-linter](import-linter.md) |
| `mdurl` | 0.1.2 | `markdown-it-py` | [import-linter](import-linter.md) |
| `msgpack` | 1.2.4 | `cachecontrol` | [pip-audit](pip-audit.md) |
| `mypy-extensions` | 1.1.0 | `mypy` | [mypy](mypy.md) |
| `packageurl-python` | 0.17.6 | `cyclonedx-python-lib` | [pip-audit](pip-audit.md) |
| `packaging` | 26.3 | `pip-audit`, `pip-requirements-parser`, `pytest` | [pip-audit](pip-audit.md) |
| `pathspec` | 1.1.1 | `mypy` | [mypy](mypy.md) |
| `pip` | 26.2.2 | `pip-api` | [pip-audit](pip-audit.md) |
| `pip-api` | 0.0.35 | `pip-audit` | [pip-audit](pip-audit.md) |
| `pip-requirements-parser` | 32.0.1 | `pip-audit` | [pip-audit](pip-audit.md) |
| `platformdirs` | 4.13.6 | `pip-audit` | [pip-audit](pip-audit.md) |
| `pluggy` | 1.7.0 | `pytest`, `pytest-cov` | [pytest](pytest.md) |
| `psycopg-binary` | 3.3.6 | `psycopg` | [psycopg](psycopg.md) |
| `py-serializable` | 2.1.0 | `cyclonedx-python-lib` | [pip-audit](pip-audit.md) |
| `pygments` | 2.21.0 | `pytest`, `rich` | [pytest](pytest.md) |
| `pyparsing` | 3.3.3 | `pip-requirements-parser` | [pip-audit](pip-audit.md) |
| `requests` | 2.34.2 | `cachecontrol`, `pip-audit` |  |
| `rich` | 15.0.0 | `import-linter`, `pip-audit` | [import-linter](import-linter.md) |
| `sortedcontainers` | 2.4.0 | `cyclonedx-python-lib` | [pip-audit](pip-audit.md) |
| `tomli` | 2.5.0 | `pip-audit` | [pip-audit](pip-audit.md) |
| `tomli-w` | 1.2.0 | `pip-audit` | [pip-audit](pip-audit.md) |
| `typing-extensions` | 4.16.0 | `cyclonedx-python-lib`, `import-linter`, `mypy`, `psycopg` | [pip-audit](pip-audit.md) |
| `tzdata` | 2026.5 | `psycopg` | [psycopg](psycopg.md) |
| `urllib3` | 2.8.0 | `requests` |  |

## Versions

Everything stated in the notes is true for the versions pinned in `requirements-dev.lock` and for PostgreSQL 18 (`postgres:18`); each note's last section links to the documentation of that version.

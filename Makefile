# make up | db | run | test | lint | down   (make help lists all)
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed

-include .env
export
PGHOST ?= localhost
PGPORT ?= 55433
PGUSER ?= lab
PGDATABASE ?= lab
ROWS ?= 2000000

# How SQL files reach the server. CI overrides this with a plain `psql` on the runner.
PSQL ?= docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)

.PHONY: help install env up db reset run measure load health lint format test test-integration test-e2e audit check docker-build psql down clean

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort

$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file

env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }

up: env ## start PostgreSQL 18 and wait until it accepts connections
	docker compose up -d --wait

# Every file is safe to run twice: IF NOT EXISTS in the schema, a seed that skips tables that have rows.
db: ## schema, ROWS events (2,000,000 by default, about 10 seconds), the lesson's inspection queries
	$(PSQL) < sql/001_schema.sql
	$(PSQL) -v rows=$(ROWS) < sql/002_seed.sql
	$(PSQL) < sql/003_queries.sql

reset: ## drop the lab's tables (make db rebuilds them)
	$(PSQL) < sql/reset.sql

run: $(STAMP) ## replay the lesson with the load running (a short baseline: about 5 minutes in all)
	$(VENV)/bin/locks-lab-run --baseline-seconds $(or $(RUN_SECONDS),20)

# The same replay with the lesson's ten-minute baseline; results.md says how busy the machine was.
measure: $(STAMP) ## replay with the lesson's ten-minute baseline (MEASURE_SECONDS=600), for figures to quote
	$(VENV)/bin/locks-lab-run --baseline-seconds $(or $(MEASURE_SECONDS),600)

load: $(STAMP) ## the load script on its own: make load SECONDS=120
	$(VENV)/bin/locks-lab-load --seconds $(or $(SECONDS),60)

health: $(STAMP) ## exit 0 when PostgreSQL holds the seeded events table
	$(VENV)/bin/locks-lab-health

lint: $(STAMP) ## ruff check, ruff format check, mypy, import-linter
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports

format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

# Unit tests need no database. Coverage is reported for the package; domain and application must stay at 95% or more.
test: $(STAMP) ## unit tests with coverage (no PostgreSQL needed)
	$(PY) -m pytest tests/unit --cov=locks_lab --cov-report=term
	$(PY) -m coverage report --include='src/locks_lab/domain/*,src/locks_lab/application/*' --fail-under=95

test-integration: $(STAMP) ## the lesson's outcomes with the load running (make up db first)
	$(PY) -m pytest tests/integration -m integration

test-e2e: $(STAMP) ## the whole replay through the command-line program (make up db first)
	$(PY) -m pytest tests/e2e -m e2e

audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock

check: lint test ## everything that needs no services

docker-build: ## build the container image of the command-line programs
	docker build -t sql-optimization-locks-and-migration:dev .

psql: ## an interactive psql session
	docker compose exec db psql -U $(PGUSER) -d $(PGDATABASE)

down: ## stop PostgreSQL and delete its data
	docker compose down -v

clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage

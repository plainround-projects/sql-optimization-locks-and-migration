# Commands for the lab. `make up`, `make db`, `make run`, `make test`, `make down` are all you need.
-include .env
PGHOST ?= localhost
PGPORT ?= 55433
PGUSER ?= lab
PGPASSWORD ?= lab
PGDATABASE ?= lab
ROWS ?= 2000000
BASELINE_SECONDS ?= 60
export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE ROWS BASELINE_SECONDS

# How SQL files reach the server. CI overrides this with a plain `psql` on the runner.
PSQL ?= docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)

VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: up db run test load psql down

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --quiet -r requirements.txt
	touch $@

up:
	docker compose up -d --wait

# Schema, then ROWS events (2,000,000 by default, about 10 seconds), then the lesson's inspection queries.
db:
	$(PSQL) < sql/001_schema.sql
	$(PSQL) -v rows=$(ROWS) < sql/002_seed.sql
	$(PSQL) < sql/003_queries.sql

# Replays the lesson with the load running throughout: baseline, the lock pile-up, the safe migration,
# the concurrent index, NOT NULL in three moves, and the plan flip. About 10 minutes by default.
run: $(VENV)/.installed
	$(PYTHON) -m scripts.run_lesson

test: $(VENV)/.installed
	$(PYTHON) -m pytest

# The load script on its own, in the foreground: make load SECONDS=120
load: $(VENV)/.installed
	$(PYTHON) -m app.load --seconds $(or $(SECONDS),60)

psql:
	docker compose exec db psql -U $(PGUSER) -d $(PGDATABASE)

# -v removes the volume too, so the next `make up` starts from an empty database.
down:
	docker compose down -v

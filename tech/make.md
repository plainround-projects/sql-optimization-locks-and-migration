# Make and the Makefile

## What it is

**Make** is a command-line tool that runs named recipes. You describe the recipes in a text file called `Makefile`, then type `make name` to run the recipe called `name`. It was invented to rebuild programs, but many projects use it as a short list of "the commands of this project": `make test`, `make lint`, `make down`.

## Why this repository uses it

The lesson has many steps (start a database, load data, replay, check). One `Makefile` gives each of them a short, fixed name, so the README can say `make up`, `make db`, `make run`, `make test`, `make lint`, `make down`, and the CI file can say `make check`. It also builds the virtual environment only when the lock file changes.

## Where it appears

| File | What it does with Make |
|---|---|
| `Makefile` | All the targets. |
| `.github/workflows/ci.yml` | Calls `make check`, `make audit`, `make db`, `make test-integration test-e2e`. |
| `README.md` | Lists the targets for readers. |

## How it works underneath

**A rule has three parts.** `target: prerequisites` on one line, then **recipe** lines below it, each starting with a **tab character** (not spaces). The target is a name, usually a file name. The prerequisites are the things it depends on. The recipe is the list of shell commands that produce the target.

**Make runs a rule only when it needs to.** When the target is a *file*, Make compares file times: if the target does not exist, or any prerequisite is newer, it runs the recipe; otherwise it prints nothing and skips it. Before running a rule Make first makes sure each prerequisite is up to date, by running their rules. That is how `up: env` runs `env` before `up`.

**Phony targets.** A target like `test` is not a file, it is an action. Listing it after `.PHONY:` tells Make "never look for a file called `test`; always run the recipe". Without that, a file named `test` in the folder would make `make test` say "up to date" and do nothing.

**Recipe lines run in separate shells.** Make starts `/bin/sh -c "line"` for each recipe line, one after the other. A `cd` on one line does not carry to the next. If a line exits with a non-zero code, Make stops and reports an error. A line starting with `@` is not echoed before it runs; a line starting with `-` may fail without stopping Make.

**Variables.** `NAME := value` sets it immediately. `NAME ?= value` sets it only if it is not already set (by you on the command line, `make NAME=other`, or by the environment). `$(NAME)` reads it. `export` on a line of its own passes every Make variable to the programs the recipes start, as environment variables.

**Automatic variables.** Inside a recipe, `$@` is the target's name, `$<` the first prerequisite, `$^` all prerequisites.

**Functions.** `$(shell cmd)` runs a command and returns its output; `$(or a,b)` returns `a` if it is not empty, else `b`; `$(firstword ...)`, `$(MAKEFILE_LIST)` (the list of makefiles read) and others.

**Includes.** `include file` reads another file as if its lines were here; `-include file` does the same but silently ignores a missing file. A `.env` file with `NAME=value` lines is valid makefile syntax, which is how this repository reads its settings.

**Comments** start with `#`. The `##` after a target is only a convention: a grep in the `help` rule picks those lines to print a menu.

**Versions.** The `make` on a Mac is GNU Make 3.81 (very old); Ubuntu has 4.3. This Makefile uses only features of both.

## Walkthrough of this repository's use

### Header and variables

`Makefile`, lines 1 to 13:

```make
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
```

- Line 1 is a comment that lists the six everyday targets.
- Line 2: `PYTHON ?=` picks the Python program (explained in the Bash note).
- Line 3: `VENV := .venv` is the folder name of the virtual environment.
- Line 4: `PY := $(VENV)/bin/python` is the Python inside that folder. Inside a venv, `bin/` holds its programs on Mac and Linux.
- Line 5: `STAMP := $(VENV)/.installed` is the stamp file, explained below.
- Line 7: `-include .env` reads the file `.env` (copied from `.env.example` by `make env`) as makefile lines such as `PGPASSWORD=something`. The leading `-` means "no error if it does not exist".
- Line 8: `export` on its own line makes every Make variable an environment variable of the programs the recipes start. That is how `PGPASSWORD` reaches Python and `psql`.
- Lines 9 to 13: defaults for the connection settings and `ROWS ?= 2000000`, the number of events the seed creates, with `?=` so `.env` or the command line can override them.

### The PSQL variable and .PHONY

`Makefile`, lines 15 to 18:

```make
# How SQL files reach the server. CI overrides this with a plain `psql` on the runner.
PSQL ?= docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)

.PHONY: help install env up db reset run measure load health lint format test test-integration test-e2e audit check docker-build psql down clean
```

`PSQL` is the command used to run SQL files (Bash note). Making it a variable is what lets CI replace it. `.PHONY` lists targets that are actions, not files.

### help

`Makefile`, lines 20 to 21:

```make
help: ## list the targets
	@grep -hE '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort
```

A target with the comment `## list the targets`. The recipe is the `grep | sed | sort` pipeline explained in the Bash note; `@` hides the command line.

### The stamp rule

`Makefile`, lines 23 to 29:

```make
$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file
```

This rule's target is the file `.venv/.installed`. Its prerequisites are `requirements-dev.lock` and `pyproject.toml`. If either file is newer than the stamp, or the stamp does not exist, Make runs the recipe: create the venv, install the locked tools, install this package in editable mode, then `touch` the stamp. Otherwise it skips it. `install: $(STAMP)` is a friendly name that depends on the stamp. Every target that needs Python (`run`, `measure`, `load`, `health`, `lint`, `test`...) lists `$(STAMP)` as a prerequisite, so the environment exists before they start.

### Database targets

`Makefile`, lines 31 to 44:

```make
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
```

`env` copies the example settings file once. `up: env` first runs `env`, then `docker compose up -d --wait` starts the database in the background (`-d`) and waits until its health check says it is ready (`--wait`). `db` runs three SQL files in order (the comment on line 37 says each file is safe to run twice; the second command passes `-v rows=$(ROWS)` so the seed knows how many events to create). `reset` runs `sql/reset.sql`, which drops the tables.

### Programs written in Python

`Makefile`, lines 46 to 58:

```make
run: $(STAMP) ## replay the lesson with the load running (a short baseline: about 5 minutes in all)
	$(VENV)/bin/locks-lab-run --baseline-seconds $(or $(RUN_SECONDS),20)

# The same replay with the lesson's ten-minute baseline; results.md says how busy the machine was.
measure: $(STAMP) ## replay with the lesson's ten-minute baseline (MEASURE_SECONDS=600), for figures to quote
	$(VENV)/bin/locks-lab-run --baseline-seconds $(or $(MEASURE_SECONDS),600)

load: $(STAMP) ## the load script on its own: make load SECONDS=120
	$(VENV)/bin/locks-lab-load --seconds $(or $(SECONDS),60)

health: $(STAMP) ## exit 0 when PostgreSQL holds the seeded events table
	$(VENV)/bin/locks-lab-health

```

`run`, `measure`, `load` and `health` start the commands that `pyproject.toml` defines (`locks-lab-run`, `locks-lab-load`, `locks-lab-health`) from the venv's `bin/` folder. `run` replays the lesson with a 20-second baseline (about five minutes in all); `measure` is the same with the lesson's ten-minute baseline, for figures worth quoting (the comment on line 49 says that `results.md` records how busy the machine was); `load` runs the load script alone (`make load SECONDS=120`); `health` checks the database. The `$(or $(X),default)` forms are explained in the Bash note.

### Quality targets

`Makefile`, lines 59 to 72:

```make
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
```

`lint` runs four checkers one after the other; if any fails, Make stops and the target fails. `format` lets ruff fix and reformat files. `test` runs only `tests/unit` with coverage measurement, then asks `coverage report` to print the table for the domain and application folders and fail (`--fail-under=95`) if they are covered below 95 percent.

`Makefile`, lines 74 to 83:

```make
test-integration: $(STAMP) ## the lesson's outcomes with the load running (make up db first)
	$(PY) -m pytest tests/integration -m integration

test-e2e: $(STAMP) ## the whole replay through the command-line program (make up db first)
	$(PY) -m pytest tests/e2e -m e2e

audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock

check: lint test ## everything that needs no services
```

`test-integration` and `test-e2e` select tests by the markers declared in `pyproject.toml` (`-m integration`). `audit` checks the locked dependencies for known security problems. `check: lint test` has no recipe: it only depends on two other targets, so `make check` means "do both".

### Container, shell and cleanup targets

`Makefile`, lines 85 to 95:

```make
docker-build: ## build the container image of the command-line programs
	docker build -t sql-optimization-locks-and-migration:dev .

psql: ## an interactive psql session
	docker compose exec db psql -U $(PGUSER) -d $(PGDATABASE)

down: ## stop PostgreSQL and delete its data
	docker compose down -v

clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage
```

`docker-build` builds the image (Docker note). `psql` opens an interactive `psql` session in the container (note: no `-T`, because you are typing). `down` runs `docker compose down -v`: stop the containers and delete their volume, which erases the data. `clean: down` first runs `down`, then removes caches and the venv.

## Try it yourself

1. `make help` — the sorted menu of targets.
2. `make -n up` — prints `docker compose up -d --wait` (and the `.env` check) without running them.
3. `make install` twice — the first time creates `.venv`; the second prints nothing, because the stamp is newer than both prerequisites.
4. `touch pyproject.toml && make -n install` — now Make says it would run the install again, because `pyproject.toml` is newer than the stamp.
5. `make PYTHON=python3.12 -n install` — shows the command lines with a different Python substituted.

## Mistakes people make

- Spaces instead of a tab at the start of a recipe line: Make says `missing separator`.
- Forgetting `.PHONY` for action targets.
- Expecting `cd dir` on one line to affect the next line.
- Putting a `$` in a shell command without doubling it: Make treats `$x` as its own variable; to give the shell a `$x`, write `$$x`.
- Treating `make` like a script that always re-does everything; it skips targets that are files and already up to date.
- Typing a variable on the command line after the target (`make test PYTHON=...`): it works, but it is easy to forget that it also overrides the file's `?=` line.

**How this repository avoids them.** Every recipe line starts with a tab, as the editor config (`[Makefile] indent_style = tab`) demands. All action targets are in `.PHONY`. No recipe relies on a `cd`. The stamp file makes the install rule skip work that is already done. `make check` is defined as dependencies so there is one place that says what "check" means.

## Check yourself

1. Why must the recipe lines begin with a tab? *Make's syntax uses the tab to tell a recipe line from other text; spaces give `missing separator`.*
2. What does `.PHONY: test` tell Make? *That `test` is the name of an action, not a file, so the recipe always runs.*
3. What is the difference between `:=` and `?=`? *`:=` always assigns; `?=` assigns only if the variable has no value yet.*
4. Why does `cd build` on one recipe line not affect the next line? *Each line is run by its own new shell process, which ends when the line ends.*
5. When does Make skip a rule whose target is a file? *When the file exists and is not older than any of its prerequisites.*

## Further reading

- GNU Make manual: https://www.gnu.org/software/make/manual/make.html ("Rules", "Writing Recipes", "How to Use Variables", "Functions for Transforming Text"). This repository's `Makefile` is valid for GNU Make 3.81 (macOS) and 4.x (Ubuntu).

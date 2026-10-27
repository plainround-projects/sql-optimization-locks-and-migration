# Bash and the shell

## What it is

A **terminal** is a window where you type a line of text and press Enter to make the computer do something. The program inside the terminal that reads your line and runs it is called a **shell**. **Bash** is the most common shell on Linux. Its simpler core, the **POSIX shell** (program name `sh`), is what the `Makefile` of this repository and its CI file use: the tool `make` runs every command line with `/bin/sh`. On a Mac `/bin/sh` is a restricted Bash; on the Ubuntu machines of GitHub Actions it is a smaller shell called `dash`. So the commands here use only features that all of them share. (The default interactive shell of a Mac is `zsh`, which understands the same basics.)

A shell is also a small programming language. A line such as `cp a b` means "run the program called `cp` and give it two words, `a` and `b`". A file full of such lines is a **shell script**.

## Why this repository uses it

Every action in the lab is one short command: start the database, load the data, run the lesson, run the checks. This repository does not have stand-alone `.sh` script files. The shell commands live in three places: the recipes of the `Makefile`, the `run:` lines of the CI file, and the `RUN` and `HEALTHCHECK` lines of the `Dockerfile`. Reading them is how you see exactly what `make db` or `make lint` does.

## Where it appears

| File | What the shell does there |
|---|---|
| `Makefile` | Each indented recipe line is a shell command. A few are shell programs of their own: the `help` pipeline, the `.env` check, the `rm -rf` of `clean`. |
| `.github/workflows/ci.yml` | `run:` lines are shell commands that GitHub's Ubuntu machines run. |
| `Dockerfile` | `RUN pip install ...` and `RUN useradd ...` are shell commands run while the image is built; `ENV` has a shell-style line continuation. |
| `docker-compose.yml` | `CMD-SHELL` in the health check hands a command line to the container's shell. |

## How it works underneath

**A command is a program plus its arguments.** The shell splits your line into words at spaces. The first word is the program name. The shell looks for a file with that name in the folders listed in the `PATH` variable and starts it as a new **process**. A process is one running copy of a program. The other words are the **arguments** the program receives.

**Quotes control splitting.** `echo "a b"` passes one argument, `a b`. `echo a b` passes two. Single quotes `'...'` keep every character exactly as typed. Double quotes `"..."` keep spaces together but still let `$variable` and `$(command)` be replaced.

**Variables.** `NAME=value` stores text. `$NAME` or `${NAME}` is replaced with it. A variable marked **exported** is copied into the environment of every program started afterwards, so those programs can read it (see the environment-variables note).

**Command substitution.** `$(command)` runs the command and puts its printed output in its place.

**Exit codes.** Every process ends with a number, its **exit code**. `0` means success. Any other number means some kind of failure. The shell keeps the last one in `$?`.

**Combining commands.**

- `a && b` runs `b` only if `a` succeeded (exit code 0).
- `a || b` runs `b` only if `a` failed.
- `a ; b` runs `b` afterwards whatever happened to `a`.
- `a | b` is a **pipe**: whatever `a` prints becomes the input of `b`, and both run at the same time.
- `{ a; b; }` is a **group**: the commands inside count as one command. The spaces and the final `;` are required.

**Redirection.** Every process starts with three channels: **standard input** (where it reads, channel 0), **standard output** (where it prints results, channel 1) and **standard error** (where it prints problems, channel 2). `command < file` feeds a file into standard input. `command > file` writes standard output to a file (replacing it). `command >> file` appends. `2>&1` sends channel 2 to the same place as channel 1. `/dev/null` is a special file that throws away everything written to it.

**Tests.** `[ -f path ]` is a command named `[` that exits 0 if `path` is an existing regular file. `[ -z "$x" ]` tests for empty text.

**Wildcards.** `*.sql` is replaced by the shell with the names of all matching files, sorted. `**` and brace forms such as `{a,b}` also exist.

**Comments.** Everything from `#` to the end of the line is ignored.

**Script safety options.** Scripts often begin with `set -euo pipefail`. `-e` stops the script at the first failing command, `-u` makes an unset variable an error, and `pipefail` makes a pipe fail if any part of it fails. This repository has no stand-alone `.sh` files, so none of its commands needs them; the commands live in the `Makefile`, which runs each recipe line in its own shell (see the Make note).

## Walkthrough of this repository's use

Make runs each recipe line with `/bin/sh`, one fresh shell per line. A leading `@` is not shell: it is a Make instruction that means "do not print the command before running it". A leading `-` would mean "ignore a failure". The Make note explains both.

### Choosing a Python

`Makefile`, lines 2 to 2:

```make
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
```

`$(shell ...)` is Make asking a shell to run something and use what it prints. Inside it, `command -v NAME` prints the full path of the program `NAME` if the shell can find it and exits 0, or prints nothing and exits 1 if it cannot. `a || b || c` means: try `a`; only if it failed, try `b`; only if that failed, try `c`. So this line picks the first of `python3.13`, `python3.12`, `python3` that exists, and stores its path in the Make variable `PYTHON`. `?=` means "only if `PYTHON` is not already set", so `make PYTHON=/usr/bin/python3.12 install` overrides it.

### The `help` target

`Makefile`, lines 21 to 21:

```make
	@grep -hE '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort
```

This is a **pipeline**: three programs connected by `|`. The first, `grep`, searches text. `-E` turns on extended regular expressions (a mini-language for patterns), and `-h` hides the file name that `grep` would otherwise put in front of each match when it is given more than one file (`$(MAKEFILE_LIST)` is the list of every makefile Make has read, which includes `.env` because of `-include .env`). The pattern, in single quotes so the shell does not touch it, is `^[a-z0-9-]+:.*## `: a line that starts (`^`) with one or more (`+`) lowercase letters, digits or hyphens, then a colon, then anything (`.*`), then the two characters `##` and a space. Those are exactly the target lines that carry a `## description` comment. The second program, `sed -E 's/:.*## /\t/'`, is a stream editor; its `s/old/new/` command replaces the first match of the pattern `:.*## ` (from the first colon to the `## `) by a tab (`\t`), which leaves `target<TAB>description`. The third, `sort`, puts the lines in alphabetical order. Nothing is written to a file; the final text goes to the terminal.

### The virtual environment recipe

`Makefile`, lines 23 to 27:

```make
$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@
```

- `$(PYTHON) -m venv $(VENV)` runs Python's built-in module `venv` to create a folder `.venv` that holds a private copy of the Python tools.
- `$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock` runs the `pip` program inside that folder. `-q` is "quiet". The other two flags are explained in the pip note.
- `touch $@` creates an empty file, or updates the time of an existing one. `$@` is Make's name for "the target of this rule", here `.venv/.installed`. That file is the **stamp**: Make compares its time with the time of `requirements-dev.lock` and `pyproject.toml` to decide whether the install must run again.

### The `.env` check

`Makefile`, lines 31 to 32:

```make
env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
```

`[ -f .env ]` is true when a regular file named `.env` exists. `||` runs what follows only when that test failed, that is, when the file is missing. `{ cp .env.example .env; echo "created .env from .env.example"; }` is a group: first `cp` copies the example file to `.env`, then `echo` prints a message. Because of the `||`, nothing happens if `.env` already exists, which makes the target safe to run any number of times. The leading `@` hides the command text. The semicolon after `echo ...` is required before the closing brace.

### Feeding SQL files to the database

`Makefile`, lines 16 to 16:

```make
PSQL ?= docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)
```
`Makefile`, lines 39 to 41:

```make
	$(PSQL) < sql/001_schema.sql
	$(PSQL) -v rows=$(ROWS) < sql/002_seed.sql
	$(PSQL) < sql/003_queries.sql
```

`PSQL` is a Make variable holding a command line; Make pastes it in front of each `<`. The middle line adds `-v rows=$(ROWS)`: the psql flag `-v name=value` sets a psql variable, here `rows` (2,000,000 unless you run `ROWS=50000000 make db`), which the seed file reads as `:rows`. `docker compose exec -T db psql ...` runs the program `psql` inside the already running `db` container. `-T` tells Docker not to allocate a pseudo-terminal, which is needed because the input is a file, not a keyboard. The `psql` flags are in the psql note. `< sql/001_schema.sql` is **input redirection**: the shell opens the file and connects it to the standard input of the command, so `psql` reads the SQL text as if you had typed it. The three lines run in order, and Make stops at the first one that exits with a non-zero code.

In CI the same lines run with `PSQL="psql -X -q -v ON_ERROR_STOP=1"` (line 54 of `ci.yml`), a plain local `psql` talking to a service container. The double quotes keep the whole string together as one argument to `make`.

### Quoting a list of paths

`Makefile`, lines 71 to 72:

```make
	$(PY) -m pytest tests/unit --cov=locks_lab --cov-report=term
	$(PY) -m coverage report --include='src/locks_lab/domain/*,src/locks_lab/application/*' --fail-under=95
```

`--include='src/locks_lab/domain/*,src/locks_lab/application/*'` uses single quotes so the shell does **not** expand the `*` into file names; `coverage` needs to receive the star itself and match it. `--cov=locks_lab` has no quotes because it has nothing special in it.

### Removing files

`Makefile`, lines 94 to 95:

```make
clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage
```

`rm -rf` removes files: `-r` means "recursively, folders and everything in them", `-f` means "do not complain if something is missing". The names are the local caches and the virtual environment. `clean: down` means the target `down` runs first (it stops the database).

### Choosing the length of a run

`Makefile`, lines 46 to 54:

```make
run: $(STAMP) ## replay the lesson with the load running (a short baseline: about 5 minutes in all)
	$(VENV)/bin/locks-lab-run --baseline-seconds $(or $(RUN_SECONDS),20)

# The same replay with the lesson's ten-minute baseline; results.md says how busy the machine was.
measure: $(STAMP) ## replay with the lesson's ten-minute baseline (MEASURE_SECONDS=600), for figures to quote
	$(VENV)/bin/locks-lab-run --baseline-seconds $(or $(MEASURE_SECONDS),600)

load: $(STAMP) ## the load script on its own: make load SECONDS=120
	$(VENV)/bin/locks-lab-load --seconds $(or $(SECONDS),60)
```

`$(or $(RUN_SECONDS),20)` is a Make function: it returns `$(RUN_SECONDS)` if that variable is set and not empty, otherwise the text `20`. So `make run` is `.venv/bin/locks-lab-run --baseline-seconds 20`, `RUN_SECONDS=60 make run` uses 60, and `make measure` uses 600 unless `MEASURE_SECONDS` says otherwise. `make load SECONDS=120` sets the Make variable `SECONDS` for that run (`$(or $(SECONDS),60)`). The `$(VENV)/bin/` prefix is a path: the shell starts that exact program from the virtual environment.

### Container build lines

`Dockerfile`, lines 6 to 9:

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
```
`Dockerfile`, lines 20 to 22:

```dockerfile
RUN useradd --system --uid 10001 --no-create-home app
USER app
ENV LAB_SQL_DIR=/app/sql
```

A backslash at the end of a line means "the command continues on the next line", so lines 6 to 9 are one `ENV` instruction that sets four environment variables. `useradd --system --uid 10001 --no-create-home app` is a Linux program that creates a user account: `--system` marks it as a service account, `--uid 10001` fixes its numeric id, `--no-create-home` skips making a home folder.

### The health check in the compose file

`docker-compose.yml`, lines 32 to 36:

```yaml
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U ${PGUSER:-lab} -d ${PGDATABASE:-lab}"]
      interval: 2s
      timeout: 3s
      retries: 30
```

`CMD-SHELL` means: give the next string to the container's `/bin/sh -c`. `pg_isready` is a small PostgreSQL program that asks a server "are you accepting connections?" and exits 0 if yes. `-h 127.0.0.1` says to use the network address of the container itself, `-U` is the user, `-d` is the database. `${PGUSER:-lab}` is Compose's own variable syntax: use `PGUSER` if it is set and not empty, otherwise the text `lab`. The check runs every 2 seconds, waits up to 3 seconds for an answer, and the container is declared unhealthy after 30 failures in a row.

## Try it yourself

1. `make help` — prints each target and its description, sorted. Expect lines such as `audit<TAB>check the locked dependencies for known vulnerabilities` and `up<TAB>start PostgreSQL 18 and wait until it accepts connections`.
2. `command -v python3.13; echo "exit=$?"` — prints a path such as `/opt/homebrew/bin/python3.13` and `exit=0` if you have that Python; prints only `exit=1` if not.
3. `[ -f .env ] && echo "env exists" || echo "env missing"` — shows which branch of the `.env` check would run.
4. `grep -hE '^[a-z0-9-]+:.*## ' Makefile | sed -E 's/:.*## /\t/' | sort | head -3` — the `help` pipeline by hand, cut to three lines.
5. `make -n db` — "dry run": prints the three commands `make db` would run, without running them.

## Mistakes people make

- Forgetting quotes around a value that can contain spaces (`rm $dir` with `dir="my files"` removes two things named `my` and `files`).
- Forgetting that a pipe's exit code is the last command's, so `false | true` "succeeds" without `pipefail`.
- Using `>` where `>>` was meant, and wiping a file.
- Assuming `cd` in one command still applies in the next line when each line is a separate shell.
- Writing `[ -f file ]` without the spaces inside the brackets. `[` is a program name and `]` is its last argument, so both need spaces around them.
- Running `rm -rf` with a variable that turned out to be empty.

**How this repository avoids them.** The `.env` check uses `||`, so it never overwrites your file. Every recipe line is independent (no `cd` that a later line relies on). Paths with a star are single-quoted. `rm -rf` is given fixed names, never a variable that could be empty. `docker compose exec -T` is used because stdin is a file.

## Check yourself

1. What does the shell do with the line `cp a b` before it runs anything? *It splits it into three words, finds a program called `cp` in the folders of `PATH`, and starts it with the arguments `a` and `b`.*
2. What is the difference between `a && b` and `a ; b`? *`b` runs after `a` in both, but with `&&` only when `a` exited with 0.*
3. What does `command < file` do? *It connects the file to the command's standard input, so the command reads the file as if you had typed it.*
4. What does `$(command)` give you? *The text the command printed to standard output, put into the line in place of the `$(...)`.*
5. A command printed an error and exited with code 1. Where did the error text go, and what tells a script it failed? *Standard error (channel 2); the exit code 1, which is not 0.*

## Further reading

- GNU Bash Reference Manual, "Shell Syntax", "Shell Commands" and "Redirections": https://www.gnu.org/software/bash/manual/bash.html (the manual of the 5.x series).
- POSIX Shell Command Language, the common core of `bash` and `sh`: https://pubs.opengroup.org/onlinepubs/9699919799/utilities/V3_chap02.html

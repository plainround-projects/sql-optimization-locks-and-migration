# GitHub Actions

## What it is

**GitHub Actions** is GitHub's built-in robot. When something happens in a repository (someone pushes a commit, opens a pull request), GitHub starts a fresh, temporary computer in the cloud, copies the repository onto it and runs the steps you listed in a **workflow file**. This is called **continuous integration** (CI): every change is checked automatically by the same steps, on a clean machine, so "it works on my laptop" is not enough.

## Why this repository uses it

The repository promises that its checks pass on a clean machine. `.github/workflows/ci.yml` makes GitHub prove it on every push: one job for the checks that need no database, one job for the tests that need PostgreSQL 18.

## Where it appears

| File | What it does |
|---|---|
| `.github/workflows/ci.yml` | The whole workflow, named `ci`, with jobs `check` and `integration`. |
| `Makefile` | The targets that the workflow calls, so CI and a local run use the same commands. |

## How it works underneath

**Where the files live.** Workflow files are YAML files in `.github/workflows/`. Each file is one **workflow**.

**Triggers.** `on:` says which events start the workflow: `push` (a commit is pushed), `pull_request` (a pull request is opened or updated).

**Jobs.** A workflow has one or more `jobs:`. Each job runs on its own fresh **runner** (a virtual machine) named by `runs-on:`; `ubuntu-latest` is a Linux machine. Jobs run at the same time unless one says `needs:` another.

**Steps.** A job is a list of `steps:`, run in order on the same runner. A step is either:

- `run: command` — a shell command (the shell on Ubuntu runners is Bash; a failing command, meaning a non-zero exit code, fails the step and, by default, the job); or
- `uses: owner/repo@version` — an **action**, a reusable packaged step written by someone else. `actions/checkout@v4` copies the repository onto the runner. `actions/setup-python@v5` installs a chosen Python version and puts it on the `PATH`.

**`with:`** passes inputs to an action. **`env:`** sets environment variables for a job or a step.

**Service containers.** `services:` in a job starts extra Docker containers (a database, here) next to the job and connects them to it. The runner can reach a service on `localhost:<published port>`. `options:` are extra flags for `docker create`, such as the health-check flags.

**Result.** A job that finishes with every step green passes. GitHub shows a green check or a red cross next to the commit. Branch rules can then refuse a merge until the checks pass.

## Walkthrough of this repository's use

`.github/workflows/ci.yml`, lines 1 to 4:

```yaml
name: ci

on: [push, pull_request]

```

`name: ci` is the name shown in GitHub. `on: [push, pull_request]` starts the workflow on every push and every pull request update. `jobs:` begins the list of jobs.

`.github/workflows/ci.yml`, lines 5 to 15:

```yaml
jobs:
  check:
    name: Format, lint, types, import rules, unit tests with coverage, dependency audit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: make check
      - run: make audit
```

The first job is called `check` (its `name:` is the longer label shown on the web page). `runs-on: ubuntu-latest` picks the Linux runner. Step 1, `uses: actions/checkout@v4`, copies the repository onto the runner. Step 2, `actions/setup-python@v5` with `python-version: "3.12"` installs Python 3.12 (the oldest version the project supports, `requires-python = ">=3.12"` in `pyproject.toml`; the Dockerfile and a developer's machine may use 3.13). Step 3 runs `make check`, which is `make lint` and `make test`: ruff, ruff's format check, mypy, import-linter, then the unit tests with coverage. The first call creates the virtual environment from the hashed lock file. Step 4 runs `make audit`, which checks the locked packages for known vulnerabilities.

`.github/workflows/ci.yml`, lines 17 to 33:

```yaml
  integration:
    name: Integration and end-to-end tests (PostgreSQL 18 service container)
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:18
        ports:
          - 5432:5432
        env:
          POSTGRES_USER: lab
          POSTGRES_PASSWORD: ci-only-throwaway
          POSTGRES_DB: lab
        options: >-
          --health-cmd "pg_isready -h 127.0.0.1 -U lab -d lab"
          --health-interval 2s
          --health-timeout 3s
          --health-retries 30
```

The second job, `integration`, adds `services: postgres:` — a PostgreSQL 18 container. `ports: - 5432:5432` publishes the database on the runner's `localhost:5432`. `env:` creates the first user, password and database (the password `ci-only-throwaway` is a value that exists only inside this CI run, for a database that disappears with the runner). `options: >-` passes the health-check flags to Docker, so GitHub waits until `pg_isready` succeeds before the first step starts.

`.github/workflows/ci.yml`, lines 34 to 45:

```yaml
    env:
      PGHOST: localhost
      PGPORT: "5432"
      PGUSER: lab
      PGDATABASE: lab
      PGPASSWORD: ci-only-throwaway
      ROWS: "1000000"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
```

The job-level `env:` sets the variables that the Python programs read (`PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, `PGPASSWORD`) and `ROWS: "1000000"`, which `make db` passes to the seed (the comment on line 53 says one million rows is enough for every lock effect and keeps the job short; locally the default is two million). Because the variables are set here, no `.env` file is needed. The first two steps check out the code and install Python 3.12.

`.github/workflows/ci.yml`, lines 46 to 55:

```yaml
      # A service container cannot take server options, so set the compose file's checkpoint settings here:
      # a checkpoint that starts in the middle of the backfill would move p99 as much as the backfill does.
      - name: Space out checkpoints
        run: |
          psql -X -c "ALTER SYSTEM SET max_wal_size = '8GB'" -c "ALTER SYSTEM SET checkpoint_timeout = '15min'"
          psql -X -c "SELECT pg_reload_conf()"
      # The runner has a psql client; the service container is the database, so `make up` is not needed.
      # One million rows is enough for every lock effect and keeps the job short.
      - run: make db PSQL="psql -X -q -v ON_ERROR_STOP=1"
      - run: make test-integration test-e2e
```

A service container cannot be given server options, and the lab needs the checkpoint settings of the compose file: a checkpoint that starts in the middle of the backfill would move the measured p99 as much as the backfill does. So the step named "Space out checkpoints" sets them on the running server: `psql -X -c "ALTER SYSTEM SET max_wal_size = '8GB'" -c "ALTER SYSTEM SET checkpoint_timeout = '15min'"` writes the two values into the server's configuration, and `psql -X -c "SELECT pg_reload_conf()"` makes the server read it again without a restart. (`ALTER SYSTEM` stores a setting in a file named `postgresql.auto.conf` in the data folder; `-c` runs one SQL command; the `run: |` form is explained in the YAML note.)

Then `make db PSQL="psql -X -q -v ON_ERROR_STOP=1"` seeds the database; the runner already has a `psql` client, so `PSQL` is overridden to call it directly instead of `docker compose exec`. `make up` is not needed: the service container is the database. The last step, `make test-integration test-e2e`, runs both test targets (Make accepts several targets in one call; it runs them in order).

## Try it yourself

1. Read the workflow as a person: `cat .github/workflows/ci.yml` and find which command each `run:` line starts.
2. Run the same commands the first job runs: `make check && make audit`. If these pass locally, the `check` job should pass.
3. Start the database and run the second job's commands: `make up`, `make db`, `make test-integration test-e2e`, then `make down`.
4. After you push the repository to GitHub, the **Actions** tab shows the run; click a job to see each step's log.

## Mistakes people make

- Putting the version of Python as an unquoted number (`3.10` turns into `3.1`).
- Relying on tools that exist on the developer's machine but not on a clean runner.
- Reading a secret into a log line; secrets are masked in logs, but copies of them are not.
- Pinning an action to a moving tag without thinking about it (`@v4` follows the v4 release line).
- Making the CI steps differ from the local commands, so a green CI means little. The fix is to put the real commands in a `Makefile` and call them from the workflow.

**How this repository avoids them.** Every real command is a Makefile target, so CI cannot drift from the local commands. The Python version is quoted. The integration job brings its own database and waits for it to be healthy. The password in the workflow is a throwaway that protects nothing real. Both jobs use only `ubuntu-latest` and two standard actions.

## Check yourself

1. What starts this workflow? *A push of a commit or the opening or update of a pull request.*
2. Do two jobs share files? *No. Each job runs on its own fresh runner; files are not shared unless uploaded and downloaded explicitly.*
3. What is the difference between `run:` and `uses:`? *`run:` executes a shell command; `uses:` runs a packaged action.*
4. How does a job reach a service container? *Through the host `localhost` and the port published in `ports:`.*
5. What decides if a step failed? *A non-zero exit code of its command (or an error in the action).*

## Further reading

- Workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- Service containers: https://docs.github.com/en/actions/use-cases-and-examples/using-containerized-services/about-service-containers
- `actions/checkout`: https://github.com/actions/checkout and `actions/setup-python`: https://github.com/actions/setup-python (this repository uses the `v4` and `v5` release lines).

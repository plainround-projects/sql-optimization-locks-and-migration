# Docker Compose

## What it is

**Docker Compose** starts one or more containers from a single description file, `docker-compose.yml`. Instead of typing a long `docker run` command with many flags every time, you write the settings once in the file and type `docker compose up`. Compose is a plugin of the `docker` command (Compose "v2"; the older tool was called `docker-compose` with a hyphen).

## Why this repository uses it

The lab needs exactly one thing to be running: a PostgreSQL 18 server with settings for lock logging and for spacing out checkpoints. `docker-compose.yml` describes that server in 39 lines, so `make up` is the whole installation.

## Where it appears

| File | What it does with Compose |
|---|---|
| `docker-compose.yml` | Describes the `db` service and the `pgdata` volume. |
| `Makefile` | `up` runs `docker compose up -d --wait`; `db`, `reset` and `psql` use `docker compose exec`; `down` runs `docker compose down -v`. |
| `.env` (copied from `.env.example` by `make env`) | Provides `PGUSER`, `PGPASSWORD`, `PGDATABASE` and `PGPORT` to both Compose and the Python programs. |

## How it works underneath

**The file** is written in YAML (see the YAML note). Its top-level keys are:

- `services:` each entry is one container to run, named by you (`db`).
- `volumes:` the named volumes that services can use.
- `networks:` (not used here) custom virtual networks. When there is none, Compose makes one default network per project, and every service can reach the others by the service name.

**The project name** defaults to the name of the folder, so containers are named `<folder>-<service>-1`, and volumes `<folder>_<volume>`.

**Service keys that matter here.**

- `image:` which image to start (downloaded if missing).
- `environment:` environment variables for the program in the container.
- `ports:` `"host:container"` publishes a port.
- `command:` replaces the image's default command; a list of words is run directly, without a shell.
- `volumes:` `name:/path` mounts a volume into the container.
- `healthcheck:` a command Docker runs repeatedly to decide whether the container is `healthy`; with `test`, `interval` (time between runs), `timeout` (max time per run) and `retries` (failures in a row before `unhealthy`).
- `init: true` runs a tiny init program as the container's process 1, which starts the real program as its child. Process 1 in Linux has special duties (it must collect — "reap" — finished child processes); a database that is process 1 is not built for that. With `init: true`, the tiny init does the reaping.
- `shm_size:` the size of the shared-memory area (`/dev/shm`). PostgreSQL uses shared memory for its buffers, and Docker's default is only 64 MB.

**Variable substitution.** Compose replaces `${NAME}` in the file with the value of the environment variable (or of the same name in a `.env` file next to the compose file). `${NAME:-default}` uses `default` when `NAME` is unset or empty. `${NAME:?message}` stops with the message when `NAME` is unset or empty.

**Commands.** `docker compose up -d` creates and starts the services in the background; `--wait` waits until they are healthy. `docker compose exec service cmd` runs a command inside a running container. `docker compose down` stops and removes the containers and network; `-v` also removes the volumes (and so the data). `docker compose ps` lists them; `docker compose logs service` shows their output.

## Walkthrough of this repository's use

`docker-compose.yml`, lines 1 to 4:

```yaml
# PostgreSQL 18 lab for "Locks and migration". Lock waits are logged so the pile-up is also in the server log.
# Autovacuum stays on: its analyze threshold is part of the plan-flip story.
services:
  db:
```

Two comment lines say what is special: lock waits are logged so the pile-up of the experiments is also in the server log, and autovacuum is left on (it is part of the plan-flip story). `services:` starts the list of containers; `db:` is the name of the only one, the name the Makefile uses in `docker compose exec -T db psql`.

`docker-compose.yml`, lines 5 to 6:

```yaml
    image: postgres:18
    init: true                    # PID 1 reaps stray exec processes (health checks) instead of the postmaster
```

`image: postgres:18` is the official PostgreSQL image, major version 18. `init: true` is explained above; the comment on the line says the reason: health checks are processes started inside the container, and if the database were process 1 it would be the one collecting their exit codes, which had made it exit and restart.

`docker-compose.yml`, lines 7 to 12:

```yaml
    environment:
      POSTGRES_USER: ${PGUSER:-lab}
      POSTGRES_PASSWORD: ${PGPASSWORD:?copy .env.example to .env}
      POSTGRES_DB: ${PGDATABASE:-lab}
    ports:
      - "${PGPORT:-55433}:5432"
```

`environment:` sets variables that the image's start-up script reads to create the first user and database. `POSTGRES_USER: ${PGUSER:-lab}` means the user name is `PGUSER` if you set it, else `lab`. `POSTGRES_PASSWORD: ${PGPASSWORD:?copy .env.example to .env}` has no default: if `PGPASSWORD` is not set, Compose refuses to start and prints "copy .env.example to .env". This is how the repository avoids a built-in password. `POSTGRES_DB` is the database name. Under `ports:` the string `"${PGPORT:-55433}:5432"` publishes the container's port 5432 (PostgreSQL's standard port) as port 55433 on your machine, so Python on the host connects to `localhost:55433`. The unusual number avoids clashing with a PostgreSQL you may already have on 5432 (and with the other labs of this track, which use 55431 and 55432).

`docker-compose.yml`, lines 13 to 29:

```yaml
    command:
      - postgres
      - -c
      - max_parallel_workers_per_gather=0
      - -c
      - shared_buffers=512MB
      - -c
      - log_lock_waits=on
      - -c
      - deadlock_timeout=1s
      - -c
      - max_wal_size=8GB
      - -c
      - min_wal_size=2GB
      - -c
      - checkpoint_timeout=15min
    shm_size: 768mb
```

`command:` replaces the image's default start command. Each list item is one word, so the line is `postgres -c max_parallel_workers_per_gather=0 -c shared_buffers=512MB -c log_lock_waits=on -c deadlock_timeout=1s -c max_wal_size=8GB -c min_wal_size=2GB -c checkpoint_timeout=15min`. `-c name=value` sets a server setting.

- `max_parallel_workers_per_gather=0`: no parallel query, so plans are single-worker plans.
- `shared_buffers=512MB`: a 512 MB cache of table pages. `shm_size: 768mb` (line 29) raises the shared-memory area to 768 MB so the cache fits.
- `log_lock_waits=on`: when a session has waited for a lock longer than `deadlock_timeout`, the server writes a line to its log naming the process and the lock. Run `docker compose logs db` after the lock-queue experiment to see it.
- `deadlock_timeout=1s`: how long a session waits for a lock before the server checks for a deadlock (and, with `log_lock_waits`, logs the wait). The default is 1 s; it is written down because the lesson is about waits.
- `max_wal_size=8GB`, `min_wal_size=2GB`, `checkpoint_timeout=15min`: spacing out **checkpoints**. A checkpoint is the moment the server writes all changed pages to disk; the write-ahead log (WAL) between two checkpoints is kept as files. Without these settings a checkpoint could start in the middle of the 223-second backfill and move the load's p99 as much as the backfill does, so the measurement would blame the migration for something else. A larger `max_wal_size` and a longer `checkpoint_timeout` make checkpoints rarer; `min_wal_size` keeps 2 GB of WAL files around for reuse so the first big write does not have to create them.

`docker-compose.yml`, lines 30 to 39:

```yaml
    volumes:
      - pgdata:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U ${PGUSER:-lab} -d ${PGDATABASE:-lab}"]
      interval: 2s
      timeout: 3s
      retries: 30

volumes:
  pgdata:
```

`volumes: - pgdata:/var/lib/postgresql` mounts the named volume `pgdata` at the folder where the image keeps its data, so the data survives container restarts. The bottom `volumes:` block declares `pgdata`. The `healthcheck` is explained in the Bash note: `pg_isready` is run every 2 seconds, with a 3-second timeout, up to 30 failures in a row.

## Try it yourself

1. `docker compose config` — prints the file with every `${...}` replaced by its value (needs `.env`); shows `published: "55433"`.
2. `make up` then `docker compose ps` — shows the `db` service with status `running (healthy)`.
3. `docker compose exec db psql -U lab -d lab -c "show shared_buffers"` — prints `512MB`.
4. `docker compose exec db psql -U lab -d lab -c "show checkpoint_timeout" -c "show max_wal_size" -c "show log_lock_waits"` — prints `15min`, `8GB`, `on`.
5. `make down` — removes container and volume; `docker volume ls` no longer lists `sql-optimization-locks-and-migration_pgdata`.

## Mistakes people make

- Using spaces and tabs mixed in the YAML, or wrong indentation (YAML is indentation-sensitive).
- Publishing a database port to everyone (`0.0.0.0`) when only local use is needed. A plain `"55431:5432"` publishes on all addresses of the host; Compose also accepts `"127.0.0.1:55431:5432"` to restrict it.
- Forgetting that `down -v` deletes the data.
- Writing a default password in the file.
- Assuming "container started" means "program ready": a database needs seconds to accept connections, which is what `healthcheck` and `up --wait` solve.

**How this repository avoids them.** There is no default password (`:?`). The port is a custom number. The health check plus `--wait` make `make up` return only when the database accepts connections. `make down` is documented as deleting the data. `init: true` is set. The indentation follows `.editorconfig` (two spaces for `.yml`).

## Check yourself

1. What does `docker compose up -d --wait` do? *Starts the services in the background and returns only when their health checks pass.*
2. What is `${PGUSER:-lab}`? *The value of the environment variable `PGUSER`, or the text `lab` if it is unset or empty.*
3. What does `${PGPASSWORD:?copy .env.example to .env}` do when the variable is missing? *Compose stops with that message instead of starting the container with an empty password.*
4. Why is the data lost after `docker compose down -v` but not after `docker compose down`? *`-v` deletes the named volumes; without it the volume stays.*
5. What is `init: true` for? *It runs a tiny init program as process 1 that reaps finished child processes, so the database is not process 1.*

## Further reading

- Compose file reference: https://docs.docker.com/reference/compose-file/
- Interpolation (`${VAR:-default}`, `${VAR:?error}`): https://docs.docker.com/reference/compose-file/interpolation/
- This repository was run with Docker Compose v2.23.

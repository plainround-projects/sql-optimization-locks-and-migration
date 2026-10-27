# Docker

## What it is

**Docker** runs programs in **containers**. A container is a normal process on your computer that has been put in a box: it sees its own file system, its own list of processes and its own network, so it behaves the same everywhere and cannot easily disturb other programs. It is lighter than a virtual machine because it shares the computer's operating-system **kernel** (the core that manages memory, files and devices) instead of running a second one. On a Mac or Windows PC, Docker Desktop runs one small Linux virtual machine and starts all containers inside it.

An **image** is the frozen recipe-result a container starts from: a stack of read-only file layers plus a few settings (which program to run, which environment variables to set). A **Dockerfile** is the text file with the instructions that build an image. A **registry** (Docker Hub is the best known) is a server where images are stored under names like `postgres:18`; the part after the colon is the **tag**, usually a version.

## Why this repository uses it

The database is the one thing a learner should not have to install. `postgres:18` is started in a container by Docker Compose (see that note), so the lesson runs the same on any machine. This repository also has a `Dockerfile` for the Python command-line programs, so the replay can be run from an image as well (`make docker-build`). The lab itself does not need that image; it is there so the programs can be shipped the way production programs are.

## Where it appears

| File | What it does with Docker |
|---|---|
| `Dockerfile` | Builds an image of the Python programs: `locks-lab-run` and `locks-lab-health`. |
| `.dockerignore` | Keeps caches, `.git`, `.env` and the tests out of the build context. |
| `docker-compose.yml` | Starts the `postgres:18` image (Docker Compose note). |
| `Makefile` | `docker-build` builds the image, `psql` runs a program inside the container, `up` and `down` start and stop it. |
| `.github/workflows/ci.yml` | A `services:` entry starts `postgres:18` on the CI machine. |

## How it works underneath

**Layers and the build cache.** `docker build` reads the Dockerfile from top to bottom. Most instructions (`RUN`, `COPY`) produce a new layer. Docker remembers each layer and the exact instruction and input files that made it. On the next build it reuses a layer if nothing it depends on has changed, and it rebuilds from the first changed instruction onward. That is why files that change rarely (the lock file) are copied *before* files that change often (the source code).

**Build context.** The folder you build from (`.`) is sent to Docker as the **build context**; `COPY` can only take files from it. A `.dockerignore` file lists paths that are left out of the context, which keeps images small and keeps secrets out.

**Instructions.**

- `FROM image:tag` starts from a base image.
- `ENV NAME=value` sets an environment variable for the build and for the running container.
- `WORKDIR /dir` sets (and creates) the current folder for the instructions that follow and for the final program.
- `COPY source destination` copies files from the build context into the image.
- `RUN command` runs a shell command while building and saves the result as a layer.
- `USER name` makes all later instructions and the final program run as that user instead of the all-powerful `root` user.
- `HEALTHCHECK` tells Docker a command it can run inside the container to learn whether the program is healthy (exit 0) or not (exit 1).
- `CMD` is the default program and arguments when you start the container without giving one.
- `ENTRYPOINT` (not used here) would fix the program and treat `CMD` as its arguments.

**Running.** `docker run image` creates a container and starts the program. `--rm` deletes the container when it ends. `-e NAME=value` sets an environment variable. `--network host` makes the container share the host's network instead of its own private one. `docker ps` lists running containers; `docker logs`, `docker exec` and `docker stop` look at, enter and stop them.

**Volumes.** A container's own file system disappears with it. A **volume** is a folder managed by Docker that outlives the container; databases keep their data there.

**Ports.** Each container has its own network. To reach a program inside it from your computer you **publish** a port: `-p 55431:5432` forwards port 55431 of your computer to port 5432 of the container. A **port** is a number (0 to 65535) that tells the computer which program on it a network connection is for.

## Walkthrough of this repository's use

### The Dockerfile

`Dockerfile`, lines 1 to 4:

```dockerfile
# The command-line programs as an image. Nothing here serves traffic; the health command is the image's check.
# Run against a PostgreSQL the container can reach, for example:
#   docker run --rm --network host -e PGPASSWORD=... sql-optimization-locks-and-migration:dev locks-lab-run
FROM python:3.13.1-slim-bookworm
```

Lines 1 to 3 are comments that say what the image is for and show an example `docker run`. In the example, `--rm` deletes the container afterwards, `--network host` lets it reach the database port on the machine, `-e PGPASSWORD=...` passes the password as an environment variable (the `...` stands for the real value, which is never written in a file), and the last two words are the image name (`sql-optimization-locks-and-migration:dev`) and the command to run. Line 4, `FROM python:3.13.1-slim-bookworm`, picks the base image: Python 3.13.1 on Debian 12 ("bookworm") in its `slim` form, which leaves out compilers and documentation. The exact version in the tag is deliberate; `python:3` would change over time.

`Dockerfile`, lines 6 to 9:

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
```

One `ENV` instruction, four variables. `PYTHONDONTWRITEBYTECODE=1` stops Python from writing `.pyc` cache files. `PYTHONUNBUFFERED=1` makes Python send its printed text straight out instead of holding it in a buffer, so `docker logs` shows lines immediately. `PIP_NO_CACHE_DIR=1` makes `pip` not keep downloaded files (smaller image). `PIP_DISABLE_PIP_VERSION_CHECK=1` stops `pip` from asking the internet whether it is out of date.

`Dockerfile`, lines 11 to 13:

```dockerfile
WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
```

`WORKDIR /app` creates `/app` and makes it the current folder. `COPY requirements.lock ./` copies that one file into `/app/`. `RUN pip install --require-hashes -r requirements.lock` installs exactly the locked packages and refuses any whose downloaded file does not match the recorded hash (pip note). This is its own layer on purpose: it is rebuilt only when `requirements.lock` changes.

`Dockerfile`, lines 15 to 18:

```dockerfile
COPY pyproject.toml README.md ./
COPY src ./src
COPY sql ./sql
RUN pip install --no-deps .
```

Now the code is copied in: the project file and README (the build needs both, because `pyproject.toml` names `README.md` as the long description), the `src` folder and the `sql` folder (the program reads the SQL files at run time). `pip install --no-deps .` installs this project itself from the current folder, without touching dependencies (they are already installed and pinned).

`Dockerfile`, lines 20 to 22:

```dockerfile
RUN useradd --system --uid 10001 --no-create-home app
USER app
ENV LAB_SQL_DIR=/app/sql
```

`useradd` creates a user named `app` (shell note). `USER app` switches to it, so the program does not run as `root`. `ENV LAB_SQL_DIR=/app/sql` tells the program where its SQL files are inside the image (the Python note on `settings.py` shows the variable being read).

`Dockerfile`, lines 24 to 25:

```dockerfile
HEALTHCHECK --interval=30s --timeout=20s --retries=3 CMD ["locks-lab-health"]
CMD ["locks-lab-health"]
```

`HEALTHCHECK --interval=30s --timeout=20s --retries=3 CMD ["locks-lab-health"]` makes Docker run the health command every 30 seconds; if it takes longer than 20 seconds or fails 3 times in a row, the container is marked unhealthy. The square-bracket form is the **exec form**: a list of words run directly, with no shell. `CMD ["locks-lab-health"]` makes the health command the default when you start the container with no command, which is why the example in line 3 passes `locks-lab-run` explicitly.

### .dockerignore

`.dockerignore`, lines 1 to 10:

```gitignore
.venv
.git
.github
.mypy_cache
.ruff_cache
.pytest_cache
.import_linter_cache
.coverage
.env
tests
```

Each line is a name that is not sent to Docker. `.venv` (your local virtual environment), `.git` and `.github`, the three tool caches, `.coverage`, `.env` (it holds the database password) and `tests` (not needed at run time).

### In the Makefile

`Makefile`, lines 85 to 92:

```make
docker-build: ## build the container image of the command-line programs
	docker build -t sql-optimization-locks-and-migration:dev .

psql: ## an interactive psql session
	docker compose exec db psql -U $(PGUSER) -d $(PGDATABASE)

down: ## stop PostgreSQL and delete its data
	docker compose down -v
```

`docker build -t sql-optimization-locks-and-migration:dev .` builds an image from the Dockerfile in the current folder (`.` is the build context) and gives it the name and tag after `-t`. `docker compose down -v` stops the lab database and removes its volume (`-v`).

## Try it yourself

1. `docker --version` — prints the installed version, for example `Docker version 24.0.6`.
2. `docker ps` — lists running containers; after `make up` you will see `sql-optimization-locks-and-migration-db-1` with status `healthy`.
3. `docker compose exec db psql -U lab -d lab -c "select version()"` — runs a command inside the database container (after `make up db`).
4. `make docker-build` — builds the image; the first run downloads the Python base image, a second run is nearly instant because every layer is cached.
5. `docker image ls sql-optimization-locks-and-migration` — shows the image `sql-optimization-locks-and-migration:dev` and its size.

## Mistakes people make

- Copying the whole source before installing dependencies, so every code change reinstalls everything.
- Running as `root` inside the container.
- Using the tag `latest`, so a rebuild next month gives different software.
- Putting passwords in the Dockerfile or the image (anyone with the image can read every layer).
- Forgetting `.dockerignore`, so `.git`, caches or a local `.env` end up in the image.
- Expecting data inside a container to survive `docker rm` without a volume.

**How this repository avoids them.** The base image tag is a full version. Dependencies are installed from a hashed lock file *before* the code is copied. The program runs as the user `app`. The password is passed at run time with `-e` and is never written in a file. `.dockerignore` excludes `.env`. The database data lives in a named volume and `make down` is the one command that removes it.

## Check yourself

1. What is the difference between an image and a container? *An image is the stored, read-only result of a build; a container is a running (or stopped) process created from an image.*
2. Why does a Dockerfile copy the lock file before the source code? *So the slow install layer stays cached until the lock file itself changes.*
3. What does `USER app` change? *Every later instruction and the final program run as the unprivileged user `app` instead of `root`.*
4. What does `-p 55431:5432` do? *It forwards port 55431 on the host machine to port 5432 inside the container.*
5. Where does a database container keep data that must survive restarts? *In a volume, a folder managed by Docker outside the container's own file system.*

## Further reading

- Dockerfile reference: https://docs.docker.com/reference/dockerfile/
- Docker CLI reference (`build`, `run`): https://docs.docker.com/reference/cli/docker/
- Docker Engine 24 was used to verify this repository (`docker --version` printed 24.0.6).

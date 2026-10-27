# TOML and pyproject.toml

## What it is

**TOML** ("Tom's Obvious Minimal Language") is a text format for configuration files: sections with `name = value` lines. **`pyproject.toml`** is the one file in a Python project where the project describes itself (name, version, dependencies, how to build it) and where many tools keep their settings, each in its own `[tool.<name>]` section.

## Why this repository uses it

One file, `pyproject.toml` (92 lines), holds the project's identity and the configuration of six tools: setuptools, ruff, mypy, pytest, coverage and import-linter, plus the entry points of the three programs. Keeping them together means a reader finds every rule in one place.

## Where it appears

| File | What it holds |
|---|---|
| `pyproject.toml` | Everything listed below. |

## How it works underneath

**Syntax.**

- `key = value` sets a value. Text is in double quotes (`"3.12"`), numbers and booleans (`true`, `false`) are not quoted.
- A **list** is square brackets with commas: `["a", "b"]`; it may span lines and have a trailing comma.
- An **inline table** is curly braces on one line: `{ text = "MIT" }`.
- `[section]` starts a **table** (a group of keys). `[tool.ruff.lint]` is a table named `lint` inside `ruff` inside `tool`. The dots mean nesting.
- `[[name]]` (double brackets) adds one **item to a list of tables**. Writing `[[tool.importlinter.contracts]]` twice makes a list with two contracts.
- `#` starts a comment.

**Who reads it.** Each program opens the file itself and takes only the sections it knows. `pip` and the build backend read `[build-system]` and `[project]`; `ruff` reads `[tool.ruff]`; `pytest` reads `[tool.pytest.ini_options]`; `mypy` reads `[tool.mypy]`. Sections for other tools are ignored.

**The two standard tables.**

- `[build-system]`: which tool builds the project (`requires`) and which Python object starts the build (`build-backend`). Standardized by PEP 517/518.
- `[project]`: the project's metadata, standardized by PEP 621: `name`, `version`, `description`, `readme`, `requires-python`, `license`, `authors`, `dependencies`, and `optional-dependencies` (named groups of extra packages, here `dev`). `[project.scripts]` maps command names to Python functions: installing the project creates a program with that name that calls the function.

**Version specifiers.** `psycopg[binary]>=3.2,<4` means: package `psycopg` with its optional extra `binary`, at least 3.2 and below 4. `>=8,<10` is a range. `==3.3.6` pins one exact version.

## Walkthrough of this repository's use

### Build system

`pyproject.toml`, lines 1 to 3:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```

Building this project needs `setuptools` version 75 or newer, and the build starts at `setuptools.build_meta`. (The setuptools note explains what building means.)

### Project metadata

`pyproject.toml`, lines 5 to 13:

```toml
[project]
name = "sql-optimization-locks-and-migration"
version = "0.1.0"
description = "Changing a busy PostgreSQL table without blocking it: lock queues, safe migrations, a concurrent index, NOT NULL in three moves, and a plan flip."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [{ name = "Sumit Srivastava" }]
dependencies = ["psycopg[binary]>=3.2,<4"]
```

- `name`, `version`, `description`: the identity of the project. The name has hyphens; the importable Python package is `locks_lab` (the folder under `src/`).
- `readme = "README.md"`: the long description. This is why the Dockerfile copies `README.md` before running `pip install .`.
- `requires-python = ">=3.12"`: pip refuses to install on an older Python. The code uses Python 3.12 features such as `def retry[T](...)`.
- `license = { text = "MIT" }`: an inline table; the license is MIT (the full text is in the `LICENSE` file).
- `authors = [{ name = "Sumit Srivastava" }]`: a list with one inline table.
- `dependencies = ["psycopg[binary]>=3.2,<4"]`: the only package the programs need at run time. The extra `binary` pulls in `psycopg-binary`, a ready-made compiled part, so no C compiler is needed.

### Optional dependencies

`pyproject.toml`, lines 15 to 23:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8,<10",
    "pytest-cov>=5",
    "ruff>=0.6",
    "mypy>=1.11",
    "import-linter>=2.0",
    "pip-audit>=2.7",
]
```

The group `dev` is what you install for working on the project: `pytest` (tests), `pytest-cov` (coverage measurement), `ruff` (linter and formatter), `mypy` (type checker), `import-linter` (checks which module may import which), `pip-audit` (vulnerability check). Each has a lower bound; the exact versions are in the lock file.

### Entry points

`pyproject.toml`, lines 25 to 28:

```toml
[project.scripts]
locks-lab-run = "locks_lab.interfaces.run_cli:main"
locks-lab-load = "locks_lab.interfaces.load_cli:main"
locks-lab-health = "locks_lab.interfaces.health_cli:main"
```

Each line is `command = "module:function"`. After installation there are three programs: `locks-lab-run` imports `locks_lab.interfaces.run_cli` and calls its function `main`; `locks-lab-load` does the same for `load_cli` (the load script on its own) and `locks-lab-health` for `health_cli`. The Makefile runs them as `$(VENV)/bin/locks-lab-run`.

### Where the package is

`pyproject.toml`, lines 30 to 31:

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

`[tool.setuptools.packages.find]` tells setuptools to look for packages under the `src` folder (the "src layout"), so a test can import only the *installed* package and not whatever happens to sit in the current folder.

### ruff

`pyproject.toml`, lines 33 to 44:

```toml
[tool.ruff]
line-length = 120
target-version = "py312"
src = ["src", "tests"]
# The tech/ notes quote code fragments on purpose; ruff 0.17 would otherwise try to reformat the ones in Markdown.
extend-exclude = ["tech"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "N", "C4", "RUF", "PT", "D100", "D101", "D103", "D104"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["D"]
```

`line-length = 120` allows lines up to 120 characters. `target-version = "py312"` tells ruff which Python syntax it may assume. `src = ["src", "tests"]` tells it where first-party code lives (this is what sorts imports into the right group). `extend-exclude = ["tech"]` (with the comment above it) tells ruff to skip the `tech/` folder: these Markdown notes quote code fragments on purpose, and ruff 0.17 would otherwise check the Python blocks inside Markdown files. `select` lists the rule families to apply (ruff note). `per-file-ignores` turns off the documentation rules (`D`) for every file under `tests/`.

### mypy

`pyproject.toml`, lines 46 to 56:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
files = ["src", "tests"]

# Test functions are named for the behavior they check; annotating every one adds noise, not safety.
[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
```

`python_version = "3.12"` and `strict = true` (all the strict checks, see the mypy note). `files = ["src", "tests"]` is what `mypy` checks when run with no arguments. The `[[tool.mypy.overrides]]` item relaxes three checks for modules matching `tests.*`, with the comment on line 50 explaining why.

### pytest and coverage

`pyproject.toml`, lines 58 to 72:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "integration: needs PostgreSQL from docker-compose.yml with the seeded events table (make up db)",
    "e2e: replays the lesson through the command-line program against PostgreSQL",
]

[tool.coverage.run]
source = ["locks_lab"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = false
```

`testpaths = ["tests"]` is where pytest looks. `addopts = "-ra --strict-markers"` adds two flags to every run. `markers` declares the two custom markers `integration` and `e2e` with a description each. `[tool.coverage.run]` says: measure the package `locks_lab`, and measure branches (both outcomes of every `if`), not only lines. `[tool.coverage.report]` says: show the numbers of missing lines and also list fully covered files.

### import-linter

`pyproject.toml`, lines 74 to 92:

```toml
[tool.importlinter]
root_package = "locks_lab"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Layers: interfaces -> infrastructure -> application -> domain, never upward"
type = "layers"
layers = [
    "locks_lab.interfaces",
    "locks_lab.infrastructure",
    "locks_lab.application",
    "locks_lab.domain",
]

[[tool.importlinter.contracts]]
name = "Domain and application know nothing about PostgreSQL or threads"
type = "forbidden"
source_modules = ["locks_lab.domain", "locks_lab.application"]
forbidden_modules = ["psycopg", "threading"]
```

`root_package` names the package to analyse; `include_external_packages = true` lets contracts talk about packages such as `psycopg`. The first `[[tool.importlinter.contracts]]` is of `type = "layers"` and lists the four layers from top to bottom; the second is of `type = "forbidden"` and forbids `locks_lab.domain` and `locks_lab.application` from importing `psycopg` (the database driver) or `threading` (threads). The domain and application describe what the experiments mean and what is measured; the threads of the load and the lock experiments, and the database, are adapters.

## Try it yourself

1. `python3 -c "import tomllib, pprint; pprint.pp(tomllib.load(open('pyproject.toml','rb'))['project'])"` prints the parsed `[project]` table as a Python dictionary (`tomllib` is in Python 3.11 and newer). You see `'name': 'sql-optimization-locks-and-migration'`, the `dependencies` list, the `dev` group and the `scripts` table.
2. `ls .venv/bin | grep locks-lab` prints `locks-lab-health` and `locks-lab-run`: the two programs that `[project.scripts]` created when the project was installed.
3. `.venv/bin/pip show sql-optimization-locks-and-migration` prints the name, version `0.1.0`, the summary and the author, all taken from `[project]`.
4. `.venv/bin/ruff check --show-settings src/locks_lab/domain/plan.py | grep "formatter.line_width"` prints `formatter.line_width = 120`, the value of `line-length` from `[tool.ruff]`.

## Mistakes people make

- Writing `key: value` (YAML) instead of `key = value`.
- Forgetting the quotes around text values.
- Putting a table twice (`[tool.ruff]` defined in two places): that is an error.
- Mixing up `[x]` and `[[x]]`.
- Expecting `dependencies` ranges to give the same install on every machine; ranges allow different versions. A lock file with exact versions fixes that (see the pip note).

**How this repository avoids them.** All text is in double quotes; every table appears once; the two contracts use `[[...]]` on purpose; the dependency range is written with both a lower and an upper bound; the lock files (not the ranges) decide the installed versions.

## Check yourself

1. What is `[[tool.importlinter.contracts]]`? *One item of a list of tables; each repetition adds another contract.*
2. What does `psycopg[binary]>=3.2,<4` mean? *The package psycopg, with its extra named `binary`, at version 3.2 or higher but below 4.*
3. Which tool reads `[tool.ruff]`? *Only ruff; other tools ignore it.*
4. What does `[project.scripts]` do? *When the project is installed, it creates a command-line program with each given name that runs the named Python function.*
5. Why does the repository also keep lock files if `dependencies` already lists the packages? *The ranges allow different versions on different days; the lock file records exact versions and hashes.*

## Further reading

- TOML v1.0.0: https://toml.io/en/v1.0.0
- Writing your `pyproject.toml` (PyPA): https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
- PEP 621 (the `[project]` table): https://peps.python.org/pep-0621/

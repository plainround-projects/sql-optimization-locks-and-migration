# import-linter

## What it is

**import-linter** is a command-line tool that checks which Python modules import which other modules, and fails if the imports break rules you wrote down. It protects the *architecture* of a program: if you decide that the core business rules must not depend on the database code, import-linter turns that decision into a check that runs on every build, so nobody can break it by accident.

## Why this repository uses it

The design of this repository is "ports and adapters in four layers" (see ARCHITECTURE.md): the lesson's rules live in `domain`, the use cases in `application`, everything that touches PostgreSQL, files or signals in `infrastructure`, and the commands in `interfaces`. A diagram cannot stop someone from importing `psycopg` into `domain/plan.py`; import-linter can.

## Where it appears

| File | Role |
|---|---|
| `pyproject.toml` | `[tool.importlinter]` and two contracts. |
| `Makefile` | `lint` runs `.venv/bin/lint-imports`. |
| `.github/workflows/ci.yml` | Through `make check`. |
| `requirements-dev.lock` | `import-linter==2.15` and `grimp==3.18`. |
| `.gitignore` | Ignores `.import_linter_cache/`. |

## How it works underneath

import-linter reads every `.py` file in the package (without running it) and builds a **graph**: an arrow from module A to module B whenever A imports B (using a library called grimp). Then it checks each **contract** in your configuration against the graph. The command is `lint-imports`; it reads `[tool.importlinter]` from `pyproject.toml`.

**Top-level settings.** `root_package` names the package to analyse. `include_external_packages = true` adds third-party packages (such as `psycopg`) to the graph so contracts can mention them.

**Contract types used here.**

- `layers`: a list of modules from highest to lowest. A module may import modules in the layers *below* it, never those above. So with `interfaces → infrastructure → application → domain`, the `domain` package can import nothing from the other three, while `interfaces` may import all of them.
- `forbidden`: `source_modules` must not import `forbidden_modules`. Sub-packages count (forbidding `x.domain` also covers `x.domain.plan`) and **indirect** imports count too: if `domain` imports a helper that imports `psycopg`, the contract is broken, unless `allow_indirect_imports = true`.

**Output.** For each contract, `KEPT` or `BROKEN`; for a broken one, the chain of imports that violates it, with file and line. Exit code 0 if all are kept, non-zero if any is broken. The summary line is `Contracts: 2 kept, 0 broken.`

**Cache.** Results are cached in `.import_linter_cache/`.

## Walkthrough of this repository's use

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

- `root_package = "locks_lab"`: analyse the package under `src/`.
- `include_external_packages = true`: put `psycopg` in the graph. (`threading` is part of the standard library; it is named in the forbidden contract below and is always known.)
- Contract 1, `type = "layers"` with `layers` listed from top to bottom: `interfaces`, `infrastructure`, `application`, `domain`. Reading it: `interfaces` may import the other three; `infrastructure` may import `application` and `domain`; `application` may import `domain`; `domain` imports none of them. This is the dependency rule. Real examples that pass: `application/replay.py` imports `..domain.lesson`; `infrastructure/schema_changes.py` imports `..domain.backfill`; `interfaces/run_cli.py` imports `..application.replay`. A line such as `from ..infrastructure.postgres import session` in `domain/plan.py` would break it.
- Contract 2, `type = "forbidden"`: `locks_lab.domain` and `locks_lab.application` (the `source_modules`) must not import `psycopg` or `threading` (the `forbidden_modules`), directly or through another module. This is what keeps PostgreSQL and the threads behind the ports: the load script (`infrastructure/load_runner.py`) and the lock experiments (`infrastructure/lock_experiments.py`) use threads; the use cases in `application/` only call them through the ports.

The real output of `lint-imports`:

```text
Analyzed 55 files, 191 dependencies.
------------------------------------

Layers: interfaces -> infrastructure -> application -> domain, never upward KEPT
Domain and application know nothing about PostgreSQL or threads KEPT

Contracts: 2 kept, 0 broken.
```

The contract `name` strings are what appear in the output. By default, an import written under `if TYPE_CHECKING:` counts as an import for the contracts too (for example `application/report.py` imports `LessonResult` there, typing note), so the architecture rule holds even for imports that exist only for the type checker.

## Try it yourself

1. `.venv/bin/lint-imports` — the output above and exit code 0 (`echo $?`).
2. Break the layer rule on purpose: add the line `from locks_lab.infrastructure import postgres` under `from __future__ import annotations` in `src/locks_lab/domain/host.py` and run `.venv/bin/lint-imports --no-cache`. Both contracts are reported broken. The first says `locks_lab.domain is not allowed to import locks_lab.infrastructure:` and the chain `locks_lab.domain.host -> locks_lab.infrastructure.postgres (l.5)`. The second says `locks_lab.domain is not allowed to import psycopg:` with the chain `locks_lab.domain.host -> locks_lab.infrastructure.postgres (l.5)` then `locks_lab.infrastructure.postgres -> psycopg (l.10)` (an indirect import), and the same for `locks_lab.application`, through `application.replay -> domain.host`. The command exits with a non-zero code. Undo with `git checkout src/locks_lab/domain/host.py`.
3. `.venv/bin/lint-imports --help` lists the options: `--config`, `--contract` (check one contract), `--cache-dir`, `--no-cache`, `--debug`, `--no-logo`, `--show-timings`, `--verbose`.
4. `.venv/bin/lint-imports --show-timings` — also prints how long building the graph and checking each contract took.

## Mistakes people make

- Writing rules nobody runs: the check must be in CI.
- Setting a layer order that the code already violates, and then adding exceptions for everything.
- Forgetting `include_external_packages`, so a contract that names `psycopg` silently has nothing to check.
- Expecting import-linter to see imports done inside strings or with `importlib`.
- Treating a broken contract as a nuisance instead of a design signal.

**How this repository avoids them.** The check is in `make lint` and CI. The contracts are written before the code can drift, the external package is declared, and the layer order is the one the architecture document draws.

## Check yourself

1. What does a `layers` contract allow? *A layer may import layers below it, never layers above it.*
2. Does a `forbidden` contract check indirect imports? *Yes, by default: any chain of imports from the source to the forbidden module counts.*
3. Why `include_external_packages = true`? *So that third-party packages can be named in contracts.*
4. What does import-linter read? *The source files, building a graph of which module imports which; it does not run the code.*
5. Where does the check run in this repository? *In `make lint` and so in CI.*

## Further reading

- Import Linter 2.15 documentation: https://import-linter.readthedocs.io/en/stable/ — "Contract types: Layers", "Contract types: Forbidden", "Configuration".

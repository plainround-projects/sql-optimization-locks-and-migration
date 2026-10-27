# mypy

## What it is

**mypy** is a **static type checker** for Python. "Static" means it reads your source files without running them. It uses the type hints you wrote (see the typing note) to find mistakes such as passing text where a number is expected, calling a method that does not exist, or forgetting that a value may be `None`. If it finds none, it prints `Success: no issues found`.

## Why this repository uses it

"Typed code" in the quality bar means a checker verifies the types, not just that they are written. With `mypy --strict`, the ports, the dataclasses and the pure functions are checked everywhere, in the source and in the tests.

## Where it appears

| File | Role |
|---|---|
| `pyproject.toml` | `[tool.mypy]` and one override for the tests. |
| `Makefile` | `lint` runs `.venv/bin/mypy`. |
| `.github/workflows/ci.yml` | Through `make check`. |
| `requirements-dev.lock` | `mypy==2.4.0` and `mypy-extensions`. |
| `.gitignore` | Ignores `.mypy_cache/`. |

## How it works underneath

mypy parses every file it is asked to check, builds a picture of what type each name and expression has, and reports places where the pictures disagree. It also reads the type information of the libraries you import (many ship it, marked by a `py.typed` file; for others, separate "stub" packages such as `types-requests` provide it). Results are cached in `.mypy_cache/` so the next run is faster.

**Strict mode.** `strict = true` switches on a bundle of checks (for mypy 2.4): `--disallow-any-generics` (write `list[int]`, not bare `list`), `--disallow-subclassing-any`, `--disallow-untyped-calls` (do not call functions that have no type hints), `--disallow-untyped-defs` (every function needs hints), `--disallow-incomplete-defs` (no half-annotated functions), `--check-untyped-defs`, `--disallow-untyped-decorators`, `--warn-redundant-casts`, `--warn-unused-ignores` (a `# type: ignore` that is no longer needed is an error), `--warn-return-any` (do not return a value of unknown type from a typed function), `--no-implicit-reexport`, `--strict-equality` and `--extra-checks`.

**Common messages.** `Incompatible return value type (got "bool", expected "str")`, `Argument 1 to "f" has incompatible type "str"; expected "int"`, `Item "None" of "X | None" has no attribute "y"` (you used an optional value without checking it), `Function is missing a return type annotation`.

**Per-module overrides.** In `pyproject.toml`, a `[[tool.mypy.overrides]]` table with `module = [...]` changes options for matching modules.

**Narrowing.** After `if value is None: return`, mypy knows `value` is not `None` below it.

## Walkthrough of this repository's use

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

- `python_version = "3.12"`: check as if running on 3.12 (this makes `def retry[T]` legal and flags newer-only features).
- `strict = true`: all the strict flags in the table above.
- `files = ["src", "tests"]`: what `mypy` checks when run with no arguments (60 files).
- The `[[tool.mypy.overrides]]` item applies to modules matching `tests.*`: `disallow_untyped_defs = false`, `disallow_incomplete_defs = false` and `disallow_untyped_calls = false`. The comment (line 50) gives the reason: test functions are named for the behavior they check, so annotating every test adds noise. The source code keeps the full strictness.

How the code satisfies strict mode, in places you can open:

- Every function has parameter and return hints: `def check_health(probes: Iterable[HealthProbe]) -> HealthReport:`.
- Generics are fully written: `tuple[str, ...]`, `Mapping[str, int]`, `psycopg.Connection[Any]`.
- A value that can be absent is `X | None`, and the code checks it: `settings = load_settings()`; `if settings is None: return 2`.
- `scalar()` in `postgres.py` exists partly for mypy: `connection.execute(query).fetchone()` has the type "a row or `None`", so the helper checks for `None` once and returns `row[0]`.
- `retry[T]` carries the type through: the result of `retry(open_connection, ...)` is `psycopg.Connection[Any]`.
- There is no `# type: ignore` in `src/` (a new one would also be flagged if unused).

The command and a verified failure:

```text
$ .venv/bin/mypy
Success: no issues found in 60 source files
```

With `def loaded(self) -> str:` temporarily in `domain/host.py`:

```text
src/locks_lab/domain/host.py:18: error: Incompatible return value type (got "bool", expected "str")  [return-value]
Found 1 error in 1 file (checked 60 source files)
```

## Try it yourself

1. `.venv/bin/mypy` — `Success: no issues found in 60 source files`.
2. `.venv/bin/mypy --strict --no-incremental src/locks_lab/domain/host.py` — the same file under an explicit `--strict`.
3. The failure above: change `-> bool` to `-> str` on `loaded` and rerun; undo with `git checkout src/locks_lab/domain/host.py`.
4. `.venv/bin/mypy --help | grep -A12 -- "--strict"` — the list of flags that `strict` turns on.
5. `rm -rf .mypy_cache && .venv/bin/mypy` — a full run without cache (a few seconds).

## Mistakes people make

- Silencing errors with `# type: ignore` instead of fixing the types.
- Using `Any` to avoid thinking.
- Running mypy on only part of the code, so interfaces between checked and unchecked code go unverified.
- Letting the cache go stale after a change in configuration (delete `.mypy_cache/`).
- Annotating with a concrete type where a protocol or abstract type would allow more.

**How this repository avoids them.** No `# type: ignore`; `Any` only where the shape is open by nature (database rows, JSON documents); the one relaxation (tests) is written down with its reason, the whole of `src` and `tests` is checked in CI, and import-linter keeps the layers apart so the ports stay the only coupling.

## Check yourself

1. Does mypy run your program? *No; it only reads the source and the type hints.*
2. What does `strict = true` do? *Turns on a bundle of strict checks, notably requiring hints on every function.*
3. What does `Item "None" of "X | None" has no attribute "y"` mean? *A value that may be `None` was used without checking.*
4. Why is an unneeded `# type: ignore` reported in strict mode? *`--warn-unused-ignores` keeps stale ignores from hiding future errors.*
5. Where does mypy cache its work? *In `.mypy_cache/` (ignored by git).*

## Further reading

- mypy 2.4 documentation: https://mypy.readthedocs.io/en/stable/ — "The mypy command line" (strict flags), "The mypy configuration file", "Type hints cheat sheet".

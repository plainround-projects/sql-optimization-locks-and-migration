# ruff

## What it is

**ruff** is a fast tool that does two jobs for Python code. As a **linter** it reads your source files and reports likely mistakes and style problems (an unused import, a badly named class, a missing docstring). As a **formatter** it rewrites the files into one consistent layout (spaces around operators, line breaks, quote style) so that nobody argues about layout. It is a single program written in Rust, so it checks a whole repository in a fraction of a second.

## Why this repository uses it

The quality bar asks for "typed code + formatter + linter in CI". ruff is both the linter and the formatter, so one tool and one configuration block cover style, import order, naming, missing docstrings and likely bugs. `make lint` and CI run it, and `make format` applies it.

## Where it appears

| File | Role |
|---|---|
| `pyproject.toml` | `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]`. |
| `Makefile` | `lint` (`ruff check .` and `ruff format --check .`) and `format`. |
| `.github/workflows/ci.yml` | Runs `make check`, which runs `lint`. |
| `requirements-dev.lock` | `ruff==0.17.3`. |
| `.editorconfig` | Lines up with the formatter's choices (four-space indent). |

## How it works underneath

**Two commands.**

- `ruff check .` lints. It prints each finding as a **rule code** (a letter prefix plus digits, for example `F401`), the file and line, and a pointer to the problem. It exits with a non-zero code if it found anything. `--fix` applies the safe automatic fixes.
- `ruff format .` rewrites files. `ruff format --check .` changes nothing and fails if any file would change; this is the form used in CI. `--diff` shows what would change.

**Rule families.** Each prefix is a family borrowed from a well-known tool. You switch families on with `select` in `pyproject.toml` under `[tool.ruff.lint]`:

| Code | Family | What it catches |
|---|---|---|
| `E` | pycodestyle errors | line too long (`E501`), bad whitespace |
| `F` | Pyflakes | unused imports (`F401`), undefined names, unused variables |
| `I` | isort | imports not sorted into groups |
| `B` | flake8-bugbear | likely bugs: mutable default arguments, `raise` without `from` in an `except` |
| `UP` | pyupgrade | old syntax that newer Python replaces |
| `SIM` | flake8-simplify | needlessly complex code that can be simpler |
| `N` | pep8-naming | names that break Python's naming habits (`N818`: exception classes should end in `Error`) |
| `C4` | flake8-comprehensions | list/dict/set building that could be a comprehension or is wasteful |
| `RUF` | Ruff-specific | extra checks written for ruff |
| `PT` | flake8-pytest-style | consistent use of pytest features |
| `D100`, `D101`, `D103`, `D104` | pydocstyle | missing docstring in a public module, class, function, package |

**Settings.** `line-length` (longest allowed line), `target-version` (the Python version whose syntax may be used), `src` (folders that hold your own code, used to sort imports), `per-file-ignores` (turn rules off for some files). `extend-exclude` adds paths ruff must skip.

**Formatter behaviour.** Deterministic: the same input always gives the same output, so a second `ruff format` changes nothing. It also formats Python code blocks inside Markdown files (that is why this repository excludes its `tech/` notes).

**`# noqa`** after a line silences a rule on that line. It should be rare.

## Walkthrough of this repository's use

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

- `line-length = 120` is the longest line the formatter will produce and `E501` accepts.
- `target-version = "py312"`: ruff may assume Python 3.12 syntax (for example `def retry[T](...)`), and its `UP` rules suggest 3.12-era forms.
- `src = ["src", "tests"]`: first-party code lives here; the `I` rules sort imports into standard library, third-party and first-party groups (as in `run_cli.py`: `argparse`, `logging` first; then relative imports from the package).
- `extend-exclude = ["tech"]`: the `tech/` notes quote code fragments on purpose; ruff 0.17 would otherwise check the Python code blocks inside Markdown files. (This line was added with the `tech/` folder.)
- `select`: `E`, `F`, `I`, `B`, `UP`, `SIM`, `N`, `C4`, `RUF`, `PT` (the families in the table above) plus the four docstring rules `D100`, `D101`, `D103`, `D104`. So every module, every public class, every public function and every package needs a docstring. That is why every file under `src/` begins with a one-line triple-quoted text, and why the `__init__.py` files are not empty.
- `[tool.ruff.lint.per-file-ignores]` `"tests/**" = ["D"]`: no docstring rules for tests; their names are sentences instead.

`Makefile`, lines 59 to 67:

```make
lint: $(STAMP) ## ruff check, ruff format check, mypy, import-linter
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports

format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .
```

`make lint` runs `ruff check .` (lint, whole repository), then `ruff format --check .` (fails if any file would change). `make format` runs `ruff check --fix .` (apply safe fixes such as import sorting) and `ruff format .` (rewrite the layout).

A few rule decisions that you can see in the code:

- `N818`: the error classes are named `LabError`, `PlanParseError`, `LockWaitTimeoutError`, `UnknownMigrationError` and `LessonInterruptedError`, all ending in `Error`.
- `B904`/`B`: inside an `except`, errors are re-raised with `from error` (`LabTable.reset`, `PostgresSchemaChanges.apply`, `PostgresEventsProbe.check`).
- `UP`: type hints use `int | None`, not `Optional[int]`; `datetime.UTC`, not `timezone.utc`.
- `I`: in `run_cli.py` the imports are in three blocks separated by blank lines.
- `D`: `class ProbeResult`, `class ThreadedLoad` and each public function carry a docstring.
- `B023` (flake8-bugbear: a function defined in a loop uses the loop variable): `infrastructure/lab_table.py` line 40 has the only `# noqa: B023` of the repository. The rule worries that a lambda created inside a `for` loop sees the *last* value of the loop variable when called later. Here the lambda is called immediately, inside the same iteration (`retry(lambda: connection.execute(statement), ...)`), so the worry does not apply; the comment on the line says so. The rule code after `noqa:` names exactly which rule is silenced.

## Try it yourself

1. `.venv/bin/ruff check .` — prints `All checks passed!`.
2. `.venv/bin/ruff format --check .` — prints `N files already formatted` (66 here).
3. In a scratch file `/tmp/demo.py` with the lines `import os`, `import sys`, a blank line, and `def f(x): return x+1`, run `.venv/bin/ruff check --isolated --select F,E /tmp/demo.py`: two `F401 ... imported but unused` findings with a `--fix` hint. `.venv/bin/ruff format --isolated --diff /tmp/demo.py` shows `x+1` becoming `x + 1`. (`--isolated` ignores this repository's configuration.)
4. `.venv/bin/ruff rule D103` prints the explanation of "undocumented public function".
5. `.venv/bin/ruff linter` lists every family ruff knows, including the ones this project selects.

## Mistakes people make

- Fixing style by hand when `ruff format` would do it instantly.
- Turning on every rule at once and drowning in findings; start with a small set.
- Using `# noqa` as a habit rather than fixing the cause.
- Forgetting that `--fix` changes files: commit first.
- Running only `check` and not the formatter check in CI.

**How this repository avoids them.** A moderate rule set. One `# noqa: B023` in the source, with its reason on the same line. The formatter check is part of `make lint` and of CI. `extend-exclude` keeps the notes out of the formatter. Docstring rules apply to the code, not to the tests.

## Check yourself

1. What is the difference between `ruff check` and `ruff format`? *The first reports problems; the second rewrites the layout of the files.*
2. What does `ruff format --check` do? *Changes nothing and fails if any file is not already formatted.*
3. What does rule `F401` report? *An import that is never used.*
4. What does `per-file-ignores` do? *Switches off chosen rules for chosen files, for example docstring rules for tests.*
5. Why `select` a small set of rule families? *To get findings that matter without being swamped.*

## Further reading

- ruff documentation (0.17): https://docs.astral.sh/ruff/ — "Linter", "Formatter", "Rules" (https://docs.astral.sh/ruff/rules/), "Settings".
- `ruff rule F401` in a terminal prints the explanation of any rule.

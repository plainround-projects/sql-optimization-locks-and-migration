# Test coverage: coverage.py and pytest-cov

## What it is

**Coverage** measures which lines of your program ran while the tests ran. A line that no test ever executes is a line whose behaviour nobody has checked. **coverage.py** is the Python tool that does the measuring; **pytest-cov** is a plugin that connects it to pytest, adding the options `--cov` and `--cov-report`. A high coverage number does not prove the tests are good, but a low number proves some code is untested.

## Why this repository uses it

The quality bar says "unit + integration + one end-to-end run with coverage reported". The rule inside the repository is stricter on the part that matters most: the `domain` and `application` folders (the lesson's rules and the replay) must stay at 95 percent or more, and they are at 100.

## Where it appears

| File | Role |
|---|---|
| `pyproject.toml` | `[tool.coverage.run]` and `[tool.coverage.report]`. |
| `Makefile` | `test` runs pytest with `--cov` and then `coverage report --fail-under=95`. |
| `.gitignore` | Ignores `.coverage`. |
| `requirements-dev.lock` | `pytest-cov==7.1.0`, `coverage==7.17.0`. |

## How it works underneath

**Tracing.** While the tests run, coverage.py watches the interpreter and records every line (and, with `branch = true`, every *jump* from one line to the next) that is executed. It saves the facts in a file called `.coverage`.

**Statements and branches.** A *statement* is a line of code. A *branch* is one of the two outcomes of an `if` or the entering and leaving of a loop. With branch coverage, `if x: do()` needs a test where `x` is true and a test where it is false; line coverage alone would be satisfied by the first.

**The report.** `coverage report` prints one row per file: `Stmts` (statements), `Miss` (not executed), `Branch`, `BrPart` (branches only partly taken), `Cover` (percentage) and `Missing` (the line numbers not executed). `--include` keeps only files matching a pattern. `--fail-under=95` makes the command exit with a failure if the total is below 95 percent, which is how a build is stopped when coverage drops.

**pytest-cov options.** `--cov=package` measures that package; `--cov-report=term` prints the table in the terminal.

**Exclusions.** A line with `# pragma: no cover` is left out of the measurement; use it only for code that cannot be reached (a defensive line after a loop that always returns).

**What to cover.** Pure logic (rules, parsing, calculations) is cheap and valuable to cover fully. Code that only talks to the outside world (a database adapter) is better checked by integration tests, so a unit-test coverage gate is usually set on the inner layers only.

## Walkthrough of this repository's use

`pyproject.toml`, lines 66 to 72:

```toml
[tool.coverage.run]
source = ["locks_lab"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = false
```

`source = ["locks_lab"]` limits the measurement to this package (not the tests or libraries). `branch = true` turns on branch coverage. In the report, `show_missing = true` prints the `Missing` column and `skip_covered = false` keeps fully covered files in the table.

`Makefile`, lines 69 to 72:

```make
# Unit tests need no database. Coverage is reported for the package; domain and application must stay at 95% or more.
test: $(STAMP) ## unit tests with coverage (no PostgreSQL needed)
	$(PY) -m pytest tests/unit --cov=locks_lab --cov-report=term
	$(PY) -m coverage report --include='src/locks_lab/domain/*,src/locks_lab/application/*' --fail-under=95
```

Two commands. The first runs the unit tests with `--cov=locks_lab --cov-report=term` and prints the table for the whole package. The second asks coverage.py for a second report restricted (`--include='src/locks_lab/domain/*,src/locks_lab/application/*'`, in single quotes so the shell does not expand the stars) to the inner two layers, and `--fail-under=95` turns a low number into a failed build.

How to read the real output of `make test`:

```text
Name                                             Stmts   Miss Branch BrPart  Cover   Missing
src/locks_lab/application/replay.py               82      0      4      0   100%
src/locks_lab/application/scenarios.py            96      0      0      0   100%
src/locks_lab/domain/stats.py                     56      0      2      0   100%
src/locks_lab/infrastructure/load_runner.py      113     78     24      0    26%   43-53, 58-66, ...
src/locks_lab/infrastructure/schema_changes.py   141    106     18      0    22%   37-41, 48-49, ...
src/locks_lab/interfaces/run_cli.py               42      1      4      1    96%   69
TOTAL                                            1164    309    128      4    71%
```

`replay.py` has 82 statements, none missed, 4 branches, none partly taken, and `scenarios.py` and `stats.py` are at 100 as well: the experiments' logic and the p99 arithmetic are fully covered by unit tests that use fakes. `load_runner.py` (26%), `schema_changes.py` (22%) and `lock_experiments.py` (35%) talk to PostgreSQL and run threads, so the unit tests skip most of them; the integration tests (`make test-integration`) execute them with the load running. That is why the 95% gate is applied only to `domain` and `application`. The second report ends `TOTAL ... 100%` for those two folders. In `run_cli.py` the one missing line, 69, is the `__main__` guard.

`src/locks_lab/infrastructure/retry.py`, lines 38 to 38:

```python
    raise AssertionError("unreachable")  # pragma: no cover
```

The only `# pragma: no cover` in the package is this defensive line, which is unreachable because the loop always returns or raises.

## Try it yourself

1. `make test` — the table above, then `90 passed`, then the second report for the inner layers.
2. `.venv/bin/python -m coverage report --include='src/locks_lab/domain/*' --show-missing` — only the domain rows, with a `Missing` column (empty, as everything is covered).
3. `.venv/bin/python -m coverage html` then open `htmlcov/index.html` in a browser — every file with covered lines in green and missed ones in red (`htmlcov/` is created in the current folder; delete it afterwards).
4. In a scratch copy, delete one test from `tests/unit/domain/test_host.py` and run `make test`: the `Missing` column for `domain/host.py` lists the line numbers that lost their test, and the second report falls below 100.

## Mistakes people make

- Chasing 100 percent with tests that execute lines but assert nothing.
- Counting integration code in a unit-test gate and giving up when it is low.
- Forgetting branch coverage, so the "false" path of every `if` is untested.
- Excluding code with `# pragma: no cover` to hide gaps.

**How this repository avoids them.** The gate sits on the pure layers where coverage is cheap and meaningful. Branch coverage is on. The one `no cover` pragma is explained. Tests assert results, not merely run code.

## Check yourself

1. What does the `Miss` column count? *Statements that never ran during the tests.*
2. What does branch coverage add to line coverage? *It also requires both outcomes of each decision (and loop entry/exit) to be taken.*
3. What does `--fail-under=95` do? *Makes `coverage report` fail when total coverage is below 95 percent.*
4. Why not gate the database adapter's coverage in the unit-test run? *Its lines need a real database, which unit tests do not use; integration tests cover it.*
5. Where does coverage store what it measured? *In a file named `.coverage` in the current folder (ignored by git).*

## Further reading

- coverage.py 7.17: https://coverage.readthedocs.io/en/7.17.0/ — "Branch coverage measurement", "Configuration reference".
- pytest-cov 7.1: https://pytest-cov.readthedocs.io/en/v7.1.0/

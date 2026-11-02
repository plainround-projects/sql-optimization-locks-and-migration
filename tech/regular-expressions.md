# Regular expressions

## What it is

A **regular expression** (regex) is a short pattern that describes a family of texts, used to find or pull out pieces of text. `Execution Time: ([\d.]+) ms` describes "the words `Execution Time: `, then some digits and dots, then ` ms`", and can hand back the digits. Python has them in the standard library module `re`.

## Why this repository uses it

Three small jobs need pattern matching: reading the estimate and the node types out of the plan text of the plan-flip experiment, checking that a `LOCK_TIMEOUT` setting looks like a PostgreSQL time, and finding the `$$` markers of a function body when a `.sql` file is split into statements.

## Where it appears

| File | Patterns |
|---|---|
| `domain/flip.py` | `_NODE`, `_ESTIMATE`, `_EXECUTION` |
| `infrastructure/settings.py` | `_INTERVAL` |
| `infrastructure/sql_script.py` | `_DOLLAR_TAG` |

## How it works underneath

**Matching.** The regex engine tries the pattern at each position of the text, left to right, and reports the first place where the whole pattern fits. `re.search(pattern, text)` returns a *match object* (or `None` if nothing fits). `pattern.findall(text)` returns every match.

**Building blocks.**

| Piece | Meaning |
|---|---|
| a plain character, e.g. `a` or `:` | itself |
| `.` | any one character except a line break |
| `\d` | one digit 0 to 9 |
| `\w` | one letter, digit or underscore |
| `\s` | one space, tab or line break |
| `[abc]` | one of the characters listed; `[a-z]` a range; `[\d.]` a digit or a dot (a dot inside brackets is just a dot); `[^x]` anything but x |
| `*` | the previous piece zero or more times |
| `+` | one or more times |
| `?` | zero or one time |
| `+?` and `*?` | the same, but as few as possible ("lazy") |
| `(...)` | a **group**: remembers the text it matched, available as `match.group(1)`; with `findall`, a pattern with one group returns the group's text |
| `(?:...)` | a group for structure only, remembers nothing |
| `a|b` | a or b |
| `^` and `$` | start and end of the text, or of each line with `re.MULTILINE` |
| `\` before a symbol | the symbol itself, e.g. `\(` is a bracket |

**Raw strings.** Write patterns as `r"..."`. In a raw string a backslash is kept as typed, so `r"\d"` is the two characters `\d` that the regex engine wants. Without `r`, Python would try to read `\d` itself.

**Compiling.** `re.compile(pattern)` prepares the pattern once so it can be reused; module-level constants named `_NAME` hold them.

**Flags.** `re.MULTILINE` makes `^` match at the start of every line.

**Limits.** A regex reads text, not structure. It is a good fit for reading the fixed shapes of lines printed by a program; it is a poor fit for nested formats like HTML.

## Walkthrough of this repository's use

### Reading a plan (`domain/flip.py`)

The plan that the examples read (`sql/explain/f1_stale_statistics.txt`, the query before statistics catch up):

```text
Limit  (cost=80154.85..80154.85 rows=1 width=16) (actual time=160.418..160.426 rows=100.00 loops=1)
  Buffers: shared hit=39116 read=10990 written=254
  ->  Sort  (cost=80154.85..80154.85 rows=1 width=16) (actual time=160.417..160.420 rows=100.00 loops=1)
        Sort Key: created_at DESC
        ...
        ->  Seq Scan on events  (cost=0.00..80154.84 rows=1 width=16) (actual time=0.111..144.397 rows=150000.00 loops=1)
              Filter: ((region = 'pacific'::text) AND (city = 'seattle'::text))
              Rows Removed by Filter: 2453908
...
Execution Time: 160.440 ms
```

`src/locks_lab/domain/flip.py`, lines 11 to 13:

```python
_NODE = re.compile(r"^\s*(?:->\s*)?(Seq Scan|Index Scan Backward|Index Scan|Bitmap Heap Scan|Sort)\b", re.MULTILINE)
_ESTIMATE = re.compile(r"\(cost=[^)]*rows=(\d+)")
_EXECUTION = re.compile(r"Execution Time: ([\d.]+) ms")
```

- `_NODE = re.compile(r"^\s*(?:->\s*)?(Seq Scan|Index Scan Backward|Index Scan|Bitmap Heap Scan|Sort)\b", re.MULTILINE)` finds the five kinds of step this experiment cares about. With `re.MULTILINE`, `^` matches at the start of every line. `\s*` skips leading spaces; `(?:->\s*)?` is an optional arrow (child steps start with `->`); the group `(Seq Scan|Index Scan Backward|Index Scan|Bitmap Heap Scan|Sort)` is one of the five names (`|` means "or"; the longer `Index Scan Backward` is listed before `Index Scan` so the longer name wins); `\b` is a **word boundary**: the name must end where a word ends. The first line, `Limit`, is not in the list, so it does not match. For the plan above `findall` returns `['Sort', 'Sort', 'Sort', 'Seq Scan']`: the `Sort` step itself, and also the lines `Sort Key: created_at DESC` and `Sort Method: ...`, which start with the word `Sort` too; then the `Seq Scan` step. `parse_flip_plan` builds its tuple with `dict.fromkeys(...)`, which keeps the first of each, so the result is `('Sort', 'Seq Scan')`.
- `_ESTIMATE = re.compile(r"\(cost=[^)]*rows=(\d+)")` captures the **estimated** row count of each node. `\(cost=` is a literal opening bracket and `cost=` (the backslash makes the bracket literal), `[^)]*` is any run of characters that are not a closing bracket, then `rows=` and the digits. It skips the `(actual ...)` part because that starts with `(actual`, not `(cost`. `findall` returns every node's estimate in order, outermost first: `['1', '1', '1']` for this plan, and the code takes the last one (`estimates[-1]`), the deepest node's.
- `_EXECUTION = re.compile(r"Execution Time: ([\d.]+) ms")` captures `160.440` (digits and dots) before ` ms`.

### Checking a time setting (`infrastructure/settings.py`)

`src/locks_lab/infrastructure/settings.py`, lines 11 to 12:

```python
_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_INTERVAL = re.compile(r"^\d+(ms|s|min)$")
```

`_INTERVAL = re.compile(r"^\d+(ms|s|min)$")`: from the start (`^`) one or more digits (`\d+`), then one of `ms`, `s` or `min`, then the end (`$`). It accepts `500ms`, `2s`, `1min` and rejects `2 seconds`, `2` and `-1s`. `Settings.from_env` uses `_INTERVAL.match(lock_timeout)` and raises a `ConfigurationError` that says what a good value looks like. The check matters because the value is pasted into SQL (`SET lock_timeout = '2s'`), so it must not be arbitrary text.

### Finding `$$` in SQL (`infrastructure/sql_script.py`)

`src/locks_lab/infrastructure/sql_script.py`, lines 12 to 12:

```python
_DOLLAR_TAG = re.compile(r"\$[A-Za-z_]*\$")
```

`_DOLLAR_TAG = re.compile(r"\$[A-Za-z_]*\$")` matches PostgreSQL's dollar-quote markers: `\$` is a literal dollar sign, `[A-Za-z_]*` is zero or more letters or underscores (so `$$` and `$sql$` both match), then another `\$`. The splitter that cuts a file into statements uses `_DOLLAR_TAG.match(text, index)` to recognise the start of a body such as `DO $$ ... $$;` and then ignores semicolons inside it until the same marker appears again (the standard-library note walks through the loop).

## Try it yourself

1. `.venv/bin/python -c "from locks_lab.domain.flip import _NODE, _ESTIMATE; t = open('sql/explain/f1_stale_statistics.txt').read(); print(_NODE.findall(t), _ESTIMATE.findall(t))"` prints `['Sort', 'Sort', 'Sort', 'Seq Scan'] ['1', '1', '1']`.
2. `.venv/bin/python -c "from locks_lab.domain.flip import parse_flip_plan as p; print(p(open('sql/explain/f3_after_extended_statistics.txt').read().splitlines()))"` prints `FlipPlan(estimate=148932, nodes=('Index Scan Backward',), milliseconds=...)`: the deepest node's estimate (the `Limit` node says 100).
3. `.venv/bin/python -c "from locks_lab.infrastructure.settings import _INTERVAL as I; print([bool(I.match(x)) for x in ('500ms', '2s', '1min', '2 seconds', '2', '-1s')])"` prints `[True, True, True, False, False, False]`.
4. `LOCK_TIMEOUT="2 seconds" .venv/bin/locks-lab-health` (with the other variables loaded) prints `configuration error: LOCK_TIMEOUT must look like 500ms, 2s or 1min, got '2 seconds'` and exits with code 2.
5. `.venv/bin/python -c "from locks_lab.infrastructure.sql_script import _DOLLAR_TAG as D; print(D.match('\$sql\$ SELECT'), D.match('\$\$ x').group(0))"` prints a match for `$sql$` and then `$$`.

## Mistakes people make

- Forgetting the `r` prefix and having backslashes eaten by Python.
- Forgetting that `.` also matches a literal dot only by accident; to mean a dot, write `\.` (or `[.]`).
- Greedy matching more than intended (`.*` runs to the end of the line; `.*?` stops early).
- Using `match` (anchored at the start) where `search` was meant.
- Patterns that become unreadable; split them into named constants and test them.
- Using regex for the wrong job: JSON has `json.loads`.

**How this repository avoids them.** Patterns are compiled once as named constants; every pattern has a unit test with a realistic plan fragment (`tests/unit/domain/test_plan.py`); a plan without the expected line raises `PlanParseError` with a message instead of returning zero. JSON plans are read with real JSON parsing, not with regular expressions.

## Check yourself

1. What does `\d+` match? *One or more digits in a row.*
2. What is the difference between `(...)` and `(?:...)`? *The first remembers the matched text as a group; the second only groups.*
3. What does `findall` return for a pattern with one group? *A list of the texts matched by that group, one per match.*
4. Why write `r"\d"`? *A raw string keeps the backslash, so the regex engine receives `\d` intact.*
5. How do you match a literal dot? *`\.` or `[.]`.*

## Further reading

- Python `re` module (3.13): https://docs.python.org/3.13/library/re.html
- Regular Expression HOWTO: https://docs.python.org/3.13/howto/regex.html

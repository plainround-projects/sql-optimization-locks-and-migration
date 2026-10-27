# JSON

## What it is

**JSON** (JavaScript Object Notation) is a text format for structured data that almost every language and tool can read and write. It is the usual format for data sent between programs.

## Why this repository uses it

JSON appears in three places in this lab: the rows' `payload` column (PostgreSQL's `JSONB` type), the per-second metrics file `load-metrics.jsonl` (one JSON object per line), and the summary that the load command prints. It also quotes values in log lines.

## Where it appears

| File | Use |
|---|---|
| `sql/001_schema.sql` | `payload JSONB`. |
| `sql/002_seed.sql`, `sql/experiments/01_bulk_load_correlated_month.sql` | `jsonb_build_object('v', n % 100)`. |
| `src/locks_lab/infrastructure/load_runner.py` | Inserts `'{"v": 1}'`, updates with `payload || '{"seen": true}'`, writes `load-metrics.jsonl`. |
| `src/locks_lab/interfaces/load_cli.py` | Prints the final window summary as JSON. |
| `src/locks_lab/infrastructure/logging.py` | `json.dumps(text)` quotes log values. |
| `.gitignore` | Ignores `load-metrics.jsonl`. |

## How it works underneath

A JSON text holds one **value**, which is one of:

- an **object**: `{"name": "orders", "pages": 12}`: curly braces around `"key": value` pairs separated by commas; keys are always double-quoted text;
- an **array**: `[1, 2, 3]`: square brackets around values separated by commas;
- a **string**: `"text"` in double quotes, with `\"` and `\n` escapes;
- a **number**: `12`, `-3.5`, `1e6`;
- `true`, `false`, `null`.

There are no comments and no trailing commas. In Python, the standard module `json` converts: `json.loads(text)` turns JSON text into Python values (objects become `dict`, arrays `list`, strings `str`, numbers `int` or `float`, `null` becomes `None`) and `json.dumps(value)` does the reverse. `json.dumps("two words")` gives `"two words"` including the quotes, which is also a handy way to quote a string.

**JSON Lines (`.jsonl`)** puts one complete JSON object on each line of a file, which suits logs and measurements that are appended over time.

PostgreSQL can return query results as JSON: `EXPLAIN (FORMAT JSON)` returns the plan as a JSON document, and the `psycopg` driver decodes a `json` column into Python lists and dictionaries by itself.

## Walkthrough of this repository's use

### JSON inside the database

`src/locks_lab/infrastructure/load_runner.py`, lines 100 to 122:

```python
    # -- the three statements ---------------------------------------------------------------------------------
    def _insert(self, connection: psycopg.Connection[Any]) -> None:
        row = connection.execute(
            "INSERT INTO events (device_id, event_type, region, city, payload) "
            "VALUES (%s, %s, 'north', 'amber', '{\"v\": 1}') RETURNING id",
            (random.randint(1, 100000), random.choice(_EVENT_TYPES)),
        ).fetchone()
        if row:
            self._recent_ids.append(row[0])

    def _update(self, connection: psycopg.Connection[Any]) -> None:
        if self._recent_ids:
            connection.execute(
                "UPDATE events SET payload = payload || '{\"seen\": true}' WHERE id = %s",
                (random.choice(self._recent_ids),),
            )

    def _read(self, connection: psycopg.Connection[Any]) -> None:
        connection.execute(
            "SELECT id, event_type, created_at FROM events "
            "WHERE created_at >= now() - interval '1 minute' ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

```

The insert gives `payload` the literal `'{"v": 1}'` (a JSON object as text; PostgreSQL converts it to `JSONB` because of the column type). The update appends a key: `payload || '{"seen": true}'` merges two objects (a key in both takes the right-hand value). In Python source the quotes inside the SQL are escaped (`\\"`) because the SQL text is a Python string in double quotes.

`sql/experiments/01_bulk_load_correlated_month.sql`, lines 8 to 15:

```sql
INSERT INTO events (device_id, event_type, region, city, payload, created_at)
SELECT 1 + floor(random() * 100000)::bigint,
       (ARRAY['click','view','error','purchase','login'])[1 + floor(random() * 5)::int],
       'pacific',
       (ARRAY['seattle','portland','tacoma','spokane'])[1 + (n % 4)],
       jsonb_build_object('v', n % 100),
       timestamp '2026-10-01' + (n::numeric / 600000) * interval '30 days'
FROM generate_series(1, 600000) AS n
```

`jsonb_build_object('v', n % 100)` builds an object from key-value arguments: `{"v": 42}`.

### JSON Lines: the per-second record

`src/locks_lab/infrastructure/load_runner.py`, lines 165 to 188:

```python
    def _report(self) -> None:
        window_start = self._clock()
        while not self._stop.wait(1.0):
            now = self._clock()
            ages = [(now - started) * 1000 for started in list(self._inflight.values())]
            with self._lock:
                tick = make_tick(now, window_start, self._samples, ages)
                self._ticks.append(tick)
            window_start = now
            logger.debug("load tick", extra=fields(ops=tick.ops, errors=tick.errors, p99_ms=round(tick.p99_ms, 2)))
            self._append_metrics(
                {
                    "t": round(tick.t, 2),
                    "ops": tick.ops,
                    "errors": tick.errors,
                    "p99_ms": round(tick.p99_ms, 2),
                    "oldest_inflight_ms": round(tick.oldest_inflight_ms, 1),
                }
            )

    def _append_metrics(self, entry: dict[str, object]) -> None:
        if self._metrics_path:
            with self._metrics_path.open("a") as handle:
                handle.write(json.dumps(entry) + "\n")
```

Every second the reporter appends one line such as `{"t": 123.45, "ops": 118, "errors": 0, "p99_ms": 4.2, "oldest_inflight_ms": 3.1}`, and the replay inserts lines such as `{"t": 130.0, "mark": "step 2: a long read, then a naive ALTER behind it"}` to label the moment each step began. One object per line is the **JSON Lines** format: a program can read the file line by line (`json.loads(line)`), and a file being written still holds only complete lines. `json.dumps(entry) + "\n"` makes each line. Rounding (`round(tick.t, 2)`) keeps the lines short.

### The load command's summary

`src/locks_lab/interfaces/load_cli.py`, lines 36 to 36:

```python
        print(json.dumps(dataclasses.asdict(load.summary(start, load.now())), indent=2))
```

`dataclasses.asdict(summary)` turns the frozen `WindowSummary` into a dictionary and `json.dumps(..., indent=2)` prints it with indentation: `seconds`, `ops`, `ops_per_second`, `errors`, `p50_ms`, `p99_ms`, `max_ms`, `worst_second_p99_ms`, `stalled_seconds`.

`src/locks_lab/infrastructure/logging.py`, lines 12 to 14:

```python
def _quote(value: object) -> str:
    text = str(value)
    return json.dumps(text) if not text or any(char in text for char in ' ="\n') else text
```

`json.dumps(text)` returns the text wrapped in double quotes with special characters escaped; used when a log value contains a space, an equals sign, a double quote or a line break.

## Try it yourself

(After `make up db`.)

1. `docker compose exec db psql -U lab -d lab -t -A -c "select payload from events limit 3"` prints three objects like `{"v": 17}`.
2. `docker compose exec db psql -U lab -d lab -t -A -c "select payload || '{\"seen\": true}'::jsonb, payload -> 'v', payload ->> 'v' from events limit 1"` — the merged object, the value `17` as JSON, and `17` as text (`->` returns JSONB, `->>` text).
3. After a `make run` (it writes `load-metrics.jsonl` in the current folder; `make load` only prints): `.venv/bin/python -c "import json; [print(json.loads(l)) for l in open('load-metrics.jsonl')]"` prints one dictionary per line: the per-second records and the marks.
4. `.venv/bin/python -c "import json; print(json.dumps('two words'), json.dumps('plain'))"` prints `"two words" "plain"`.
5. `.venv/bin/locks-lab-load --seconds 5` (with `.env` loaded) ends by printing the summary as an indented JSON object.

## Mistakes people make

- Single quotes or unquoted keys (not valid JSON).
- A trailing comma after the last item.
- Expecting dates: JSON has no date type, only text.
- Reading a JSON number as exact when it is a float.
- Indexing a missing key without a fallback (`d["x"]` raises `KeyError`; `d.get("x")` returns `None`).

**How this repository avoids them.** JSON is produced and read with `json`, `jsonb_build_object` and the `||` operator, never by hand-built strings; the metrics file is append-only lines; and it is ignored by git.

## Check yourself

1. What are the two container types in JSON? *Objects (key-value pairs in braces) and arrays (lists in brackets).*
2. How does Python represent a JSON object? *As a `dict`.*
3. What does `json.dumps("a b")` return? *The text `"a b"` including the double quotes.*
4. Is `{'a': 1}` valid JSON? *No; keys and strings need double quotes.*
5. What is JSON Lines? *A file with one JSON object per line.*

## Further reading

- ECMA-404 / json.org: https://www.json.org/json-en.html
- Python `json` module: https://docs.python.org/3.13/library/json.html

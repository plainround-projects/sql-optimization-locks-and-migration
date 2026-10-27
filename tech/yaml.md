# YAML

## What it is

**YAML** is a text format for writing structured data: lists, name-and-value pairs, numbers and text, using indentation instead of brackets. Programs such as Docker Compose and GitHub Actions read YAML files as their configuration. The file extension is `.yml` or `.yaml`.

## Why this repository uses it

Two tools that this repository depends on are configured in YAML: Docker Compose (`docker-compose.yml`) and GitHub Actions (`.github/workflows/ci.yml`). Neither runs anything by itself; each reads its file and acts on it.

## Where it appears

| File | What it describes |
|---|---|
| `docker-compose.yml` | The database service and its volume. |
| `.github/workflows/ci.yml` | The two CI jobs. |

## How it works underneath

A YAML file is read by a program called a **parser**, which turns the text into data in memory made of three kinds of things:

- **Mapping**: a set of `key: value` pairs. A key is a name; the value is anything. `name: ci` is a mapping with one pair.
- **Sequence**: an ordered list. Each item starts with `- ` (dash and space). A sequence can also be written in one line with square brackets, `[push, pull_request]` (called *flow style*).
- **Scalar**: a single value: text, number (`5432`), boolean (`true`, `false`) or null.

**Indentation is the structure.** A child is indented more than its parent. Use spaces only (never tabs). Two spaces per level is the common convention, and `.editorconfig` in this repository asks for it. A sequence inside a mapping may be written at the same indentation as its key or deeper; both are valid.

**Quotes.** Plain text needs no quotes, but quote when the text could be misread: `"3.12"` stays text (unquoted `3.12` is a number, and `3.10` would become `3.1`), `"55431:5432"` stays text because `:` has a meaning in YAML. Inside double quotes `\n` means a new line; single quotes are literal.

**Comments** start with `#` (preceded by a space when after a value) and run to the end of the line.

**Multi-line text.** A `|` after the key keeps line breaks. A `>` folds the lines into one line separated by spaces. Adding `-` (`>-`, `|-`) removes the final line break.

**Gotchas of the format.** Words like `yes`, `no`, `on` and `off` were booleans in YAML 1.1 (the version many tools use), so `on:` as a *key* can be read as `true`. GitHub Actions reads `on:` correctly as the key name. Duplicated keys are an error or silently overwritten, depending on the parser.

## Walkthrough of this repository's use

### Mappings, nested

`docker-compose.yml`, lines 3 to 6:

```yaml
services:
  db:
    image: postgres:18
    init: true                    # PID 1 reaps stray exec processes (health checks) instead of the postmaster
```

`services:` is a key whose value is a mapping; `db:` (indented two spaces) is a key inside it; `image: postgres:18` and `init: true` (indented four spaces) are keys of the `db` mapping. The `:` in `postgres:18` is not followed by a space, so YAML reads `postgres:18` as one piece of text. `true` is a boolean. Everything after `#` on line 6 is a comment.

### Sequences

`docker-compose.yml`, lines 11 to 28:

```yaml
    ports:
      - "${PGPORT:-55433}:5432"
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
```

`ports:` has a sequence with one item, `- "${PGPORT:-55433}:5432"`; the quotes keep it as text, because it contains `:` and `$`. `command:` is a sequence of fifteen items, one word each. `-c` is an item of its own because the program receives each item as a separate argument. The same item style, `- -c`, reads as "dash space, then the text `-c`".

### Flow style (brackets on one line)

`docker-compose.yml`, lines 32 to 36:

```yaml
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U ${PGUSER:-lab} -d ${PGDATABASE:-lab}"]
      interval: 2s
      timeout: 3s
      retries: 30
```
`.github/workflows/ci.yml`, lines 1 to 3:

```yaml
name: ci

on: [push, pull_request]
```

`test: ["CMD-SHELL", "pg_isready ..."]` is a sequence written with brackets on one line; the quotes are needed because the second item contains spaces and `$`. `on: [push, pull_request]` is also a flow sequence, of two plain words.

### Folded text

`.github/workflows/ci.yml`, lines 29 to 33:

```yaml
        options: >-
          --health-cmd "pg_isready -h 127.0.0.1 -U lab -d lab"
          --health-interval 2s
          --health-timeout 3s
          --health-retries 30
```

`options: >-` starts a **folded block**. The next lines (indented more than `options`) are joined into a single line with spaces: `--health-cmd "pg_isready -h 127.0.0.1 -U lab -d lab" --health-interval 2s --health-timeout 3s --health-retries 30`. The `-` removes the final line break. This is how one long list of flags is kept readable.

### Literal block (line breaks kept)

`.github/workflows/ci.yml`, lines 48 to 51:

```yaml
      - name: Space out checkpoints
        run: |
          psql -X -c "ALTER SYSTEM SET max_wal_size = '8GB'" -c "ALTER SYSTEM SET checkpoint_timeout = '15min'"
          psql -X -c "SELECT pg_reload_conf()"
```

`run: |` starts a **literal block**: the lines under it, indented further than `run`, are kept exactly as written, with their line breaks, and GitHub passes the whole block to the shell as a small script of two commands. Compare it with `>-` above, which folds lines into one. Here the commands must stay on separate lines, so `|` is the right choice.

### Quoted numbers

`.github/workflows/ci.yml`, lines 34 to 40:

```yaml
    env:
      PGHOST: localhost
      PGPORT: "5432"
      PGUSER: lab
      PGDATABASE: lab
      PGPASSWORD: ci-only-throwaway
      ROWS: "1000000"
```

`PGPORT: "5432"` is quoted on purpose. Environment variables are always text; an unquoted `5432` would be read as a number and some tools would reject it. `PGUSER: lab` needs no quotes. `ROWS: "1000000"` is quoted for the same reason.

### Quoted versions

`.github/workflows/ci.yml`, lines 9 to 14:

```yaml
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: make check
```

`python-version: "3.12"` must be quoted so that it stays the text `3.12`.

## Try it yourself

1. `docker compose config` prints the whole `docker-compose.yml` after Compose has parsed it and replaced every `${...}`. It shows `init: true`, the seven `-c` settings as a list, and the port as `published: "55433"`.
2. Make a scratch file with a tab as the indentation: `printf 'services:\n\tdb:\n    image: postgres:18\n' > /tmp/tab.yml`, then `docker compose -f /tmp/tab.yml config`. The output is `yaml: line 2: found character that cannot start any token`: the parser refuses the tab.
3. Make a scratch file with `init: yes`: `printf 'services:\n  db:\n    image: postgres:18\n    init: yes\n' > /tmp/yes.yml`, then `docker compose -f /tmp/yes.yml config`. Compose prints a warning that `"yes"` is not a boolean in YAML 1.2 and shows `init: true`. Use `true`.
4. `docker compose config | grep -c "published"` prints `1`, the one published port.

## Mistakes people make

- A tab character for indentation: the parser reports an error.
- One space too many or too few, which moves a key to a different parent.
- Forgetting quotes around values with `:` or `#`, or around version numbers.
- Putting `- ` items at the wrong indentation under a key.
- Expecting YAML to run anything: it is only data. The program that reads it decides what it means.

**How this repository avoids them.** Two-space indentation everywhere, as `.editorconfig` demands (`[*.{yml,yaml,json,toml}] indent_size = 2`). Versions and ports are quoted. Long flag lists use `>-` or one-word-per-item sequences, so no line carries hidden structure.

## Check yourself

1. What are the three kinds of things in YAML? *Mappings (key: value), sequences (lists with `- `), and scalars (single values).*
2. How is `[push, pull_request]` written in block style? *As two lines: `- push` and `- pull_request`, indented under the key.*
3. Why is `python-version: "3.12"` quoted? *So it stays the text `3.12`; an unquoted `3.10` would be read as the number 3.1.*
4. What does `>-` after a key do? *It starts a block of text whose line breaks are folded into spaces and whose final line break is removed.*
5. Why can a tab not be used for indentation? *The YAML specification forbids tabs in indentation, so parsers report an error.*

## Further reading

- YAML 1.2.2 specification: https://yaml.org/spec/1.2.2/
- The Compose and GitHub Actions notes in this folder show the keys each tool expects.

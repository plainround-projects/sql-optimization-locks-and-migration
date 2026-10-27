# psql

## What it is

**`psql`** is PostgreSQL's interactive command-line client. You type SQL and see the results as text tables. It is a program separate from the server: it connects over the network (or inside the container) exactly like any other client. It also reads SQL from a file or from standard input, and it has its own commands, called **meta-commands**, that start with a backslash.

## Why this repository uses it

`psql` is how SQL files reach the database from `make`: `make db` pipes three files into it. It runs inside the database container, so no PostgreSQL client has to be installed on your machine. CI uses a `psql` that comes with the GitHub runner. The seed file also depends on three psql features that plain SQL does not have: variables, conditionals and `\gexec`.

## Where it appears

| File | Use |
|---|---|
| `Makefile` | The `PSQL` variable, and the targets `db`, `reset`, `psql`; `-v rows=$(ROWS)`. |
| `.github/workflows/ci.yml` | Overrides `PSQL` with a local `psql`; also calls `psql -X -c ...` directly to set checkpoint options. |
| `sql/002_seed.sql` | `\if :{?rows}`, `\set`, `\gset`, `\if :events_empty`, `\gexec`, `:rows`. |
| `sql/migrations/002_backfill_flagged_batch.sql` and its down | `:first_id`, `:last_id` (run by hand with `-v first_id=1 -v last_id=2000`). |
| `src/locks_lab/infrastructure/sql_script.py` | Skips meta-commands and substitutes `:name` variables when Python runs a file. |

## How it works underneath

**Connecting.** `psql -h host -p port -U user -d database` (`-h` host, `-p` port, `-U` user name, `-d` database name). The password comes from the `PGPASSWORD` environment variable, a password file, or a prompt. Inside the database's container the defaults (local socket) work.

**Giving it input.** Interactively, by typing. With `-c "SQL"`, one command. With `-f file`, or with the file redirected into standard input (`psql ... < file.sql`).

**Options used in this repository.**

- `-X`: do not read the user's `~/.psqlrc` start-up file, so results do not depend on personal settings.
- `-q`: quiet; skip the informational messages (like `CREATE TABLE`).
- `-v ON_ERROR_STOP=1`: sets the psql variable `ON_ERROR_STOP`; with it, psql stops at the first error and exits with a non-zero code (3), instead of carrying on with the rest of the file. Without it, a failing statement is reported but the script continues and the exit code is 0.
- `-U user -d database`: whom to connect as and to what.
- `-T` (a flag of `docker compose exec`, not of psql): do not allocate a terminal.

**Variables.** psql has its own variables, set with `-v name=value` or `\set name value` or `\gset`. `:name` inserts the value into SQL; `:'name'` inserts it as a quoted text literal.

**Meta-commands.** Handled by psql, never sent to the server.

- `\gset`: after a query, put the result columns into variables named like the columns.
- `\if :variable`, `\elif`, `\else`, `\endif`: run a block only if the variable is true.
- `\o file` sends query output to a file (`\o /dev/null` discards it); `\o` alone restores the screen.
- `\d table`: describe a table (columns, indexes); `\di+`: list indexes with sizes; `\dt`: list tables; `\q` quit.

**Why meta-commands matter for scripts.** They only work in psql. Another program that reads the same `.sql` file (such as this repository's Python code) must skip those lines.

## Walkthrough of this repository's use

`Makefile`, lines 15 to 16:

```make
# How SQL files reach the server. CI overrides this with a plain `psql` on the runner.
PSQL ?= docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)
```

`docker compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U $(PGUSER) -d $(PGDATABASE)`:

- `docker compose exec -T db` runs a command in the `db` container, with no terminal (the input is a file).
- `psql` is the client. `-X` ignores personal settings. `-q` silences notices. `-v ON_ERROR_STOP=1` makes any SQL error stop the run and fail the `make` target.
- `-U $(PGUSER) -d $(PGDATABASE)` are the user and database (`lab` and `lab` by default). No `-h`: inside the container psql uses the local socket. The password is not needed there because the image trusts local connections.

`Makefile`, lines 38 to 44:

```make
db: ## schema, ROWS events (2,000,000 by default, about 10 seconds), the lesson's inspection queries
	$(PSQL) < sql/001_schema.sql
	$(PSQL) -v rows=$(ROWS) < sql/002_seed.sql
	$(PSQL) < sql/003_queries.sql

reset: ## drop the lab's tables (make db rebuilds them)
	$(PSQL) < sql/reset.sql
```

`$(PSQL) < sql/001_schema.sql` etc. feed the files. The second line adds `-v rows=$(ROWS)`: `-v name=value` defines a psql **variable** `rows` (default `2000000`). `make db` stops at the first error because of `ON_ERROR_STOP`.

### Variables, conditionals and `\gexec` in the seed

`sql/002_seed.sql`, lines 1 to 14:

```sql
-- 002_seed.sql: DML. :rows events (default 2,000,000), analyzed, with region and city independent.
-- Safe to run twice: a table that already has rows is left alone (use `make reset` to start from nothing).
-- Run as: psql -v rows=50000000 < sql/002_seed.sql   (the lesson's size)
\if :{?rows}
\else
  \set rows 2000000
\endif
SELECT setseed(0.42);
SET timezone = 'UTC';

SELECT NOT EXISTS (SELECT 1 FROM events) AS events_empty \gset

-- Loaded in chunks of 1,000,000 so a 50,000,000-row load does not need one huge transaction.
\if :events_empty
```

- `\if :{?rows} ... \else \set rows 2000000 \endif`: `:{?rows}` is a psql test "is the variable `rows` defined?" (`:{?name}` expands to `TRUE` or `FALSE`). If not, `\set rows 2000000` sets a default. So `psql -v rows=50000000 < sql/002_seed.sql` loads fifty million rows and a bare run loads two million.
- `SELECT NOT EXISTS (SELECT 1 FROM events) AS events_empty \gset` runs the query and stores its result column in the variable `events_empty` (`\gset` ends the statement in place of a semicolon). `\if :events_empty` then tests it.
- `:rows` inside SQL text is replaced by psql with the variable's value before the text is sent. (Not inside quoted strings; the template below is passed through `format()` for that reason.)

`sql/002_seed.sql`, lines 15 to 29:

```sql
SELECT format($sql$
  INSERT INTO events (device_id, event_type, region, city, payload, created_at)
  SELECT 1 + floor(random() * 100000)::bigint,
         (ARRAY['click','view','error','purchase','login'])[1 + floor(random() * 5)::int],
         (ARRAY['north','south','east','west','central'])[1 + floor(random() * 5)::int],
         (ARRAY['amber','birch','cedar','delta','ember','fjord','grove','haven','iris','jade',
                'kiln','lark','mesa','nova','opal','pine','quartz','reed','slate','tide',
                'umber','vale','willow','xenon','yarrow','zephyr','aspen','brook','cliff','dune',
                'elm','frost','glen','hill','isle','jetty','knoll','lake','moor','nook'])[1 + floor(random() * 40)::int],
         jsonb_build_object('v', n %% 100),
         timestamp '2026-09-01' + (n::numeric / %s) * interval '30 days'
  FROM generate_series(%s, %s) AS n
$sql$, :rows, chunk_start, least(chunk_start + 999999, :rows)) AS statement
FROM generate_series(1, :rows, 1000000) AS chunk_start
\gexec
```

`\gexec` (after the query, in place of `;`) takes every value in the result and **executes it as an SQL statement**. The query produces one `INSERT` text per chunk of a million rows, so the file generates and runs its own statements.

### Variables in migration files

`sql/migrations/002_backfill_flagged_batch.sql`, lines 1 to 9:

```sql
-- Step 3, backfill: one batch. The application runs it for id ranges with a pause between batches.
-- The value is derived from existing data, which is why a backfill is needed at all (a constant default
-- would need none in PostgreSQL 11 and later). Only rows still NULL are touched, so a batch can be repeated.
-- Run by hand: psql -v first_id=1 -v last_id=2000 < this file. Undo: down/002_backfill_flagged_batch.down.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
UPDATE events SET flagged = (event_type = 'error')
WHERE id BETWEEN :first_id AND :last_id AND flagged IS NULL;
COMMIT;
```

`:first_id` and `:last_id` are psql variables: run by hand as `psql -v first_id=1 -v last_id=2000 < sql/migrations/002_backfill_flagged_batch.sql`. The Python runner does the same job itself (it replaces `:first_id` with a psycopg placeholder and passes the values; standard-library note), because it does not run psql.

### In CI

`.github/workflows/ci.yml`, lines 48 to 51:

```yaml
      - name: Space out checkpoints
        run: |
          psql -X -c "ALTER SYSTEM SET max_wal_size = '8GB'" -c "ALTER SYSTEM SET checkpoint_timeout = '15min'"
          psql -X -c "SELECT pg_reload_conf()"
```

`psql -X -c "ALTER SYSTEM SET max_wal_size = '8GB'" -c "ALTER SYSTEM SET checkpoint_timeout = '15min'"`: `-c "command"` runs one command; several `-c` options run in order. The runner's `psql` reads `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE` and `PGPASSWORD` from the job's environment, which is why no connection flags are needed.

### The interactive shell

`Makefile`, lines 88 to 89:

```make
psql: ## an interactive psql session
	docker compose exec db psql -U $(PGUSER) -d $(PGDATABASE)
```

`make psql` opens an interactive session: no `-T`, so Docker allocates a terminal; no `-X`/`-q`, so you get the normal friendly behaviour. Type `\d events`, a query, `\q` to leave.

## Try it yourself

(After `make up db`.)

1. `make psql`, then type `\dt` and press Enter: lists `events` and `lab_meta`. `\d events` shows the columns and indexes. `\q` quits.
2. `echo "select 1 as one;" | docker compose exec -T db psql -X -q -U lab -d lab` prints a one-row table.
3. `printf 'select 1/0;\nselect 2 as two;\n' | docker compose exec -T db psql -X -q -U lab -d lab; echo "exit=$?"` prints the error and still runs `select 2`; exit code 0. Now add `-v ON_ERROR_STOP=1` and it stops after the error with exit code 3.
4. `printf 'select 1 as flag \\gset\n\\echo :flag\n' | docker compose exec -T db psql -X -q -U lab -d lab` prints `1`.
5. `printf "select format('select %%s + 1', n) from generate_series(1, 3) n \\\\gexec\n" | docker compose exec -T db psql -X -q -U lab -d lab` runs three generated statements and prints `2`, `3`, `4`.
6. `printf '\\if :{?rows}\n\\echo defined\n\\else\n\\echo not defined\n\\endif\n' | docker compose exec -T db psql -X -q -U lab -d lab` prints `not defined`; add `-v rows=5` before `-U` and it prints `defined`.

## Mistakes people make

- Running a script without `ON_ERROR_STOP` and not noticing that half of it failed.
- Expecting `\gset` or `\if` to work in other clients.
- Forgetting the semicolon at the end of a statement typed interactively (psql waits for more input).
- Pasting a large script with a tab character, which triggers completion.
- Leaving a transaction open in an interactive session.

**How this repository avoids them.** `ON_ERROR_STOP=1` in the `PSQL` variable. `-X` for repeatability. The seed uses `\if` so repeating `make db` does not double the data. The Python runner strips the meta-commands it cannot run.

## Check yourself

1. What does `-v ON_ERROR_STOP=1` change? *psql stops at the first error and exits with a non-zero code.*
2. What does `psql ... < file.sql` do? *Feeds the file to psql's standard input, so it runs the file's statements.*
3. What does `\gset` do? *Stores the columns of the last query's result in psql variables.*
4. Why does `-X` help repeatability? *It stops psql from reading the personal `~/.psqlrc` file.*
5. Where do meta-commands run? *In psql itself, never on the server.*

## Further reading

- PostgreSQL 18, `psql`: https://www.postgresql.org/docs/18/app-psql.html (options and "Meta-Commands").

# Git

## What it is

**Git** is a tool that records the history of a folder of files. Each time you reach a good state you save a **commit**: a snapshot of every tracked file together with a message, your name, the time, and a pointer to the previous commit. The whole history lives in a hidden folder `.git/` inside the project (this folder is a **repository**). With git you can see what changed and why, go back to an older state, and work on several versions of the project in parallel (**branches**).

## Why this repository uses it

The repository is meant to be cloned and run: the history shows how it was built, the `.gitignore` keeps generated files out, and the quality bar says the working tree is clean after the final commit. The verification starts with a fresh `git clone`.

## Where it appears

| File | Role |
|---|---|
| `.git/` | The history (not shown in the tree). |
| `.gitignore` | What git must not track. |
| `.dockerignore` | The same idea for Docker builds (Docker note). |

## How it works underneath

**Three places.** The **working folder** holds the files you edit. The **staging area** (the index) holds the changes you have chosen for the next commit (`git add file`). The **repository** holds the commits (`git commit`).

**Commits are identified by hashes.** A commit's id is a 40-character fingerprint computed from its content and its parent; `git log --oneline` shows the first 7 characters. History is a chain of commits, each pointing to its parent. A **branch** is a movable label on a commit (`main` is the usual main one); `HEAD` is "where you are now".

**Useful commands.** `git status` (what changed), `git diff` (the changes), `git add`, `git commit -m "message"`, `git log --oneline`, `git show <id>` (one commit), `git checkout -- file` or `git restore file` (discard edits to a file), `git clone source` (copy a repository), `git push` / `git pull` (exchange commits with another copy, such as GitHub).

**What not to store.** Generated files (caches, virtual environments), machine-specific settings and secrets do not belong in history. A file named **`.gitignore`** lists patterns of paths that git must ignore:

- `name/` ignores a folder called `name` anywhere.
- `*.pyc` ignores every file with that ending (`*` matches any characters).
- `.env` ignores that exact file name.
- `#` starts a comment.

An ignored file is not shown by `git status` and is never added by `git add .`. Ignoring only affects files not yet tracked.

**Commit messages.** A short first line saying what the change does, optionally a longer explanation. Trailers such as `Co-Authored-By: Name <email>` at the end credit helpers.

**Working tree clean.** `git status` printing nothing (or "nothing to commit, working tree clean") means every change has been committed.

## Walkthrough of this repository's use

`.gitignore`, lines 1 to 15:

```gitignore
.venv/
__pycache__/
*.pyc
*.egg-info/
build/
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.import_linter_cache/
.coverage
.env
.DS_Store
logs/
.omc/
```

Line by line:

- `.venv/`: the virtual environment (large, machine-specific, rebuilt by `make install`).
- `__pycache__/` and `*.pyc`: the byte-code cache that Python writes next to the source.
- `*.egg-info/`: metadata folders that an editable install creates under `src/`.
- `build/` and `dist/`: output folders of packaging tools.
- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.import_linter_cache/`: caches of the four tools.
- `.coverage`: the coverage data file.
- `.env`: your local settings file with the password. It is not committed; `.env.example` is.
- `.DS_Store`: a file macOS writes into folders.
- `logs/`: a folder for log files, should a program write any.
- `.omc/`: local state of an assistant tool, not part of the project.

What is committed instead: the source, the SQL, the tests, the lock files, the configuration, the documentation. Everything generated can be rebuilt from those.

Reading the history:

```text
git log --oneline
```

lists the commits newest first; each line is a short id and a message such as "Add the project tooling: pyproject, hashed lock files, Makefile, Dockerfile, CI" or "Replace app/ and scripts/ with a layered package: domain, application, infrastructure, interfaces". The commits are split by purpose (tooling, code, SQL, tests, documentation, results) so each one can be read and reverted on its own. Commit messages end with a `Co-Authored-By:` line crediting the assistant that helped write the change.

## Try it yourself

1. `git status` — prints `On branch main` and either lists changes or `nothing to commit, working tree clean`.
2. `git log --oneline | head` — the last ten commits.
3. `git check-ignore -v .venv .env` — for each path prints the `.gitignore` line that ignores it, such as `.gitignore:1:.venv/	.venv`.
4. `git ls-files | head -20` — the files git tracks; `.venv` and `.env` are not among them.
5. `git clone . /tmp/clone-check && ls -a /tmp/clone-check` — a fresh copy has no `.venv`, no `.env` and no caches; `rm -rf /tmp/clone-check` afterwards.

## Mistakes people make

- Committing secrets or large generated files; removing them later does not remove them from history.
- Committing everything in one giant commit with the message "changes".
- Using `git add .` without checking `git status`.
- Forgetting that `.gitignore` does not un-track a file that was already committed.
- Rewriting history that others have already pulled.

**How this repository avoids them.** Secrets and generated files are ignored; `.env.example` shows the variables without secrets; commits are small and named for their purpose; and the final state is a clean tree.

## Check yourself

1. What is a commit? *A snapshot of the tracked files with a message, an author, a time and a pointer to its parent commit.*
2. What does `.gitignore` do? *Lists path patterns that git ignores, so they are not shown or added.*
3. What is the staging area for? *Choosing exactly which changes go into the next commit.*
4. Why is `.venv/` in `.gitignore`? *It is a large, machine-specific, generated folder that can be recreated from the lock file.*
5. What does a clean `git status` tell you? *All changes are committed (or ignored).*

## Further reading

- Pro Git book: https://git-scm.com/book/en/v2 — "Git Basics" and "Recording Changes to the Repository".
- gitignore pattern format: https://git-scm.com/docs/gitignore (Git 2.50 was used here).

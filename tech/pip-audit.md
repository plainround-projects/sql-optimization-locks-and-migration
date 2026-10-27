# pip-audit

## What it is

**pip-audit** checks the Python packages a project depends on against public lists of **known vulnerabilities** (security bugs that someone has reported and numbered, such as `PYSEC-2024-...` or `GHSA-...`). If a pinned version is on the list, it says so and tells which version fixes it. This is called **dependency auditing** and is one defence against **supply-chain** problems: the risk that code you did not write is the weak spot.

## Why this repository uses it

The quality bar asks for "pinned dependencies with an audit step". The pins are the lock files; the audit step is `make audit`, which CI runs on every push.

## Where it appears

| File | Role |
|---|---|
| `Makefile` | The `audit` target. |
| `.github/workflows/ci.yml` | `make audit` is the last step of the `check` job. |
| `requirements-dev.lock` | The file that is audited (the run-time packages and the tools); it also pins `pip-audit==2.10.1` and its own dependencies. |

## How it works underneath

For every package and exact version in the input, pip-audit asks a vulnerability database over the internet (by default the Python Packaging Advisory Database through PyPI's JSON API; OSV is an option) whether that version is affected. It prints a table of findings, or `No known vulnerabilities found`. The exit code is 0 when nothing is found and non-zero otherwise, so CI can fail on it.

**Input.** `-r requirements-file` audits the packages named in the file. By default pip-audit would let `pip` work out the full list of dependencies of what is named; two flags avoid that:

- `--no-deps`: audit only the lines in the file, and require them all to be pinned with `==`. Use it when the file is already a complete lock.
- `--disable-pip`: do not call `pip` at all (it normally creates a temporary environment to resolve dependencies).

pip-audit may print a warning that `--no-deps` is supported but users are encouraged to fully hash their pinned dependencies; this repository's lock files are fully hashed, so the warning is informational.

**Needs the network.** Without internet access the command fails; it cannot say "safe" about what it cannot check.

**A result is a moment in time.** A package with no known problem today may have one tomorrow, so the audit runs on every CI build.

## Walkthrough of this repository's use

`Makefile`, lines 80 to 81:

```make
audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock
```

`$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock`:

- `-r requirements-dev.lock` audits the packages in the dev lock (about fifty).
- `--no-deps` says the file is complete and pinned; pip-audit checks each line and does not look for more.
- `--disable-pip` keeps pip out of it, which is faster and avoids creating a temporary environment.

Real output on 2026-10-27:

```text
.venv/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock
WARNING:pip_audit._cli:--no-deps is supported, but users are encouraged to fully hash their pinned dependencies
WARNING:pip_audit._cli:Consider using a tool like `pip-compile`: https://pip-tools.readthedocs.io/en/latest/#using-hashes
No known vulnerabilities found
```

The two warnings are about hashing; the lock is fully hashed (pip-and-venv note), and pip-audit only recommends. The last line is the result; the command exits 0. When it finds something, it prints a table with the package, the installed version, the vulnerability id and the fixed version, and exits non-zero, which turns the CI job red. The fix is to regenerate the lock (uv note) so the package moves to a fixed version.

## Try it yourself

1. `make audit` — the output above (needs the internet).
2. `echo $?` straight after it — `0`.
3. `.venv/bin/pip-audit --help` — lists the options (`-r`, `--no-deps`, `--disable-pip`, `--ignore-vuln`, `--fix`, `-f` for the output format).
4. In a scratch folder, make a file `old.txt` containing the single line `requests==2.19.0`, then run `.venv/bin/pip-audit --no-deps --disable-pip -r old.txt`. That very old version of `requests` has known problems, so you see `Found 10 known vulnerabilities in 1 package` followed by a table (`Name`, `Version`, `ID` such as `PYSEC-2018-28`, `Fix Versions` such as `2.20.0`), and a non-zero exit code.

## Mistakes people make

- Auditing the installed environment instead of the lock file, and so checking something other than what ships.
- Ignoring a finding without a recorded reason (`--ignore-vuln ID` should come with a comment).
- Treating "no known vulnerabilities" as "secure".
- Never refreshing the lock file, so audits keep failing on old versions.

**How this repository avoids them.** The audit runs on the lock file, not on whatever happens to be installed. It is in CI, so a new advisory turns the next build red. No `--ignore-vuln` is used.

## Check yourself

1. What does pip-audit compare? *Each pinned package version against a database of known vulnerabilities.*
2. Why `--no-deps` here? *The lock file already lists every package, so there is nothing for pip to resolve.*
3. Why does the command need internet access? *The vulnerability data is fetched from an online service.*
4. What does a non-zero exit code mean? *At least one vulnerable package was found (or the check could not run).*
5. Why run it on every build and not once? *New vulnerabilities are published every day.*

## Further reading

- pip-audit 2.10 on PyPI and GitHub: https://pypi.org/project/pip-audit/ and https://github.com/pypa/pip-audit
- Python Packaging Advisory Database: https://github.com/pypa/advisory-database

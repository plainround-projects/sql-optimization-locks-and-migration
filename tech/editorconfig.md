# EditorConfig

## What it is

**EditorConfig** is a tiny file format, in a file called `.editorconfig`, that tells text editors how to write files in a project: which character set, which line endings, how to indent, whether to trim trailing spaces. Most editors (VS Code, IntelliJ, Vim, Sublime) read it automatically or with a small plug-in, so every contributor's editor produces the same bytes no matter their personal settings.

## Why this repository uses it

The repository contains files with different indentation rules (Python with four spaces, YAML, JSON and TOML with two, a Makefile with tabs). `.editorconfig` records them once so any editor does the right thing.

## Where it appears

| File | Role |
|---|---|
| `.editorconfig` | The whole configuration (18 lines). |

## How it works underneath

The file is a list of **sections**. A section header is a file pattern in square brackets (`[*.md]`, `[Makefile]`, `[*.{yml,yaml,json,toml}]` where braces list alternatives); under it come `key = value` lines that apply to files matching the pattern. The editor looks for `.editorconfig` in the folder of the file being edited and in each parent folder; `root = true` at the top tells it to stop looking further up. Later sections override earlier ones for the keys they set.

**Keys.** `charset` (text encoding, `utf-8`), `end_of_line` (`lf` is the single line-feed that Linux and macOS use; Windows uses `crlf`), `insert_final_newline` (end the file with a line break), `trim_trailing_whitespace` (remove blanks at line ends), `indent_style` (`space` or `tab`), `indent_size` (how many columns one indent level is).

EditorConfig does not enforce anything by itself: it is advice that editors follow when saving. Formatters such as ruff are the enforcement for code.

## Walkthrough of this repository's use

`.editorconfig`, lines 1 to 18:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{yml,yaml,json,toml}]
indent_size = 2

[Makefile]
indent_style = tab

[*.md]
trim_trailing_whitespace = false
```

- `root = true`: this is the top-level file; no parent folder is consulted.
- `[*]` applies to every file: `charset = utf-8` (the character set), `end_of_line = lf`, `insert_final_newline = true` (a file ends with a line break), `trim_trailing_whitespace = true`, `indent_style = space`, `indent_size = 4` (Python's standard).
- `[*.{yml,yaml,json,toml}]`: for these four kinds of file the indent is 2 columns (the YAML and Compose files, `pyproject.toml`).
- `[Makefile]`: `indent_style = tab`, because the `make` tool needs a tab before each recipe line (Make note).
- `[*.md]`: `trim_trailing_whitespace = false`, so the Markdown files keep deliberate trailing spaces (Markdown note).

The formatter (`ruff format`) is what enforces the Python part; the other files rely on editors that read this file.

## Try it yourself

1. `cat .editorconfig` — the 18 lines above.
2. `file Makefile` and `grep -c "$(printf '\t')" Makefile` — the second prints the number of lines containing a tab (the recipe lines).
3. `grep -n " $" src/locks_lab/domain/host.py` — prints nothing: no line ends with a space.
4. `tail -c 1 README.md | xxd` — the last byte is `0a`, a line feed: the file ends with a final newline.

## Mistakes people make

- Mixed line endings (`crlf` and `lf`) that make every line look changed in a diff.
- Trailing spaces in Markdown, where two spaces at the end of a line can mean a line break (so Markdown sections often disable trimming).
- Tabs in files that need spaces (YAML) and spaces in files that need tabs (Makefiles).
- Assuming it is enforced: an editor without the plug-in ignores it.

**How this repository avoids them.** One file states the rules; Makefile and Markdown have their own sections; the Python rules are enforced by the formatter in CI.

## Check yourself

1. What is the purpose of `.editorconfig`? *To make every editor save files with the same encoding, line endings and indentation.*
2. What does `root = true` do? *Stops editors from looking in parent folders for more settings.*
3. Why does the Makefile section say `indent_style = tab`? *Make requires a tab character at the start of recipe lines.*
4. Why disable trailing-space trimming for Markdown? *Two trailing spaces can be an intentional line break in Markdown.*
5. What is `lf`? *The single line-feed character that ends a line on Linux and macOS.*

## Further reading

- EditorConfig specification and properties: https://spec.editorconfig.org/ and https://editorconfig.org/

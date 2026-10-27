"""Read the repository's SQL files and run them statement by statement."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import psycopg

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_]*\$")


def split_statements(sql_text: str) -> list[str]:
    """Split SQL on semicolons, ignoring `--` comments, quoted text and `$$ ... $$` bodies.

    psql meta-commands (lines starting with a backslash) are not SQL and are dropped.
    """
    lines = [line.split("--", 1)[0] for line in sql_text.splitlines() if not line.lstrip().startswith("\\")]
    text = "\n".join(lines)
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    dollar: str | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if dollar:
            if text.startswith(dollar, index):
                current.append(dollar)
                index += len(dollar)
                dollar = None
                continue
        elif quote:
            quote = None if character == quote else quote
        elif character in ("'", '"'):
            quote = character
        elif character == "$" and (tag := _DOLLAR_TAG.match(text, index)):
            dollar = tag.group(0)
            current.append(dollar)
            index += len(dollar)
            continue
        elif character == ";":
            statements.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(character)
        index += 1
    return [statement for statement in statements if statement]


def run_file(connection: psycopg.Connection[Any], path: Path, params: Mapping[str, int] | None = None) -> list[Any]:
    """Run every statement of a file on one connection; return the rows of the last one that returns rows.

    The files use psql's `:name` variables; `params` fills them (as `%(name)s`) when the caller runs the file.
    """
    text = path.read_text()
    for name in params or {}:
        text = text.replace(f":{name}", f"%({name})s")
    rows: list[Any] = []
    for statement in split_statements(text):
        uses_params = params is not None and "%(" in statement
        cursor = connection.execute(statement, params) if uses_params else connection.execute(statement)
        if cursor.description:
            rows = cursor.fetchall()
    return rows

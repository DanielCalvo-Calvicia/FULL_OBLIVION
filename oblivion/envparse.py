"""Reading and writing ``.env`` text. Standard library only, no imports from this package.

It is used by the deploy tool and, through ``service_runner.py``, inside a service's own Python. The files the tool
writes are read by python-dotenv (six services), by Brain's own reader and by ``service_runner.py``, so a value is
written in a form all of them read back the same.
"""

from __future__ import annotations

import re

_INLINE_COMMENT = re.compile(r"(^|\s)#.*$")


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        values[key.strip()] = _value(value)
    return values


def _value(raw: str) -> str:
    """The value of ``KEY=<raw>``: quotes removed, and for unquoted values an inline ``# comment`` dropped.

    A ``#`` starts a comment only at the start or after whitespace (``abc#def`` is a value), like dotenv.
    """
    raw = raw.strip()
    if raw[:1] == '"':
        decoded = _double_quoted(raw)
        if decoded is not None:
            return decoded
    elif raw[:1] == "'":
        closing = raw.find("'", 1)
        if closing != -1:
            return raw[1:closing]  # whatever follows the closing quote is a comment
    return _INLINE_COMMENT.sub("", raw).strip()


_ESCAPES = {"n": "\n", "\\": "\\", '"': '"'}


def _double_quoted(raw: str) -> str | None:
    """The text of a leading ``"..."`` with ``\\n``, ``\\\\`` and ``\\"`` decoded; None when it is never closed."""
    out: list[str] = []
    i = 1
    while i < len(raw):
        char = raw[i]
        if char == "\\" and i + 1 < len(raw):
            out.append(_ESCAPES.get(raw[i + 1], "\\" + raw[i + 1]))
            i += 2
            continue
        if char == '"':
            return "".join(out)
        out.append(char)
        i += 1
    return None


def render_value(value: str) -> str:
    """``value`` as it is written after ``KEY=``.

    Plain values stay plain (a JSON value with spaces and double quotes is fine unquoted). A value that a reader could
    change is single-quoted, which python-dotenv takes literally: one with a ``#`` (a comment to an unquoted reader),
    a ``$`` (variable expansion), edge whitespace, or a quote at the start.
    """
    risky = value != value.strip() or "#" in value or "$" in value or value[:1] in ("'", '"') or "\n" in value
    if not risky:
        return value
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'

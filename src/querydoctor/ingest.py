"""Query ingestion from SQL files, query logs and raw text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from querydoctor.errors import QueryDoctorError

_TITLE = re.compile(r"^\s*--\s*(?:name|title)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_STATEMENT_START = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


@dataclass(frozen=True)
class QueryInput:
    """A query waiting to be analyzed."""

    id: str
    sql: str
    title: str | None = None


def _split_script(text: str) -> list[str]:
    """Split on semicolons that are outside quotes and comments."""
    chunks: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)
    quote: str | None = None
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == "-" and nxt == "-":
            end = text.find("\n", i)
            end = n if end == -1 else end
            buf.append(text[i:end])
            i = end
            continue
        elif ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            i = end
            continue
        elif ch == ";":
            chunks.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    chunks.append("".join(buf))
    return chunks


def _line_per_query(text: str) -> list[str]:
    """Fallback for query logs with one statement per line and no semicolons."""
    return [ln for ln in text.splitlines() if _STATEMENT_START.match(ln)]


def parse_queries(text: str) -> list[QueryInput]:
    """Parse a SQL script or query log into individual queries with optional ``-- name:`` titles."""
    chunks = _split_script(text)
    non_empty = [c for c in chunks if _body(c)]
    if len(non_empty) <= 1 and ";" not in text:
        per_line = _line_per_query(text)
        if len(per_line) > 1:
            chunks = per_line
    queries: list[QueryInput] = []
    for chunk in chunks:
        body = _body(chunk)
        if not body:
            continue
        title = next(
            (m.group(1) for ln in chunk.splitlines() if (m := _TITLE.match(ln))),
            None,
        )
        queries.append(QueryInput(id=f"q{len(queries) + 1}", sql=body, title=title))
    return queries


def _body(chunk: str) -> str:
    lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith("--")]
    return "\n".join(lines).strip()


def read_queries(path: Path) -> list[QueryInput]:
    """Read queries from a ``.sql`` or plain-text query log file."""
    if not path.exists():
        raise QueryDoctorError(f"Query file not found: {path}")
    queries = parse_queries(path.read_text(encoding="utf-8"))
    if not queries:
        raise QueryDoctorError(f"No queries found in {path}.")
    return queries

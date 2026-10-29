from __future__ import annotations

from pathlib import Path

import pytest

from querydoctor.errors import QueryDoctorError
from querydoctor.ingest import parse_queries, read_queries


def test_splits_on_semicolons_and_reads_titles() -> None:
    text = "-- name: First\nSELECT 1;\n-- title: Second\nSELECT 2;"
    queries = parse_queries(text)
    assert [q.title for q in queries] == ["First", "Second"]
    assert [q.sql for q in queries] == ["SELECT 1", "SELECT 2"]
    assert [q.id for q in queries] == ["q1", "q2"]


def test_semicolon_inside_string_is_kept() -> None:
    queries = parse_queries("SELECT 'a;b' AS x; SELECT 2")
    assert len(queries) == 2
    assert "a;b" in queries[0].sql


def test_block_comments_are_ignored() -> None:
    queries = parse_queries("/* note; here */ SELECT 1")
    assert [q.sql for q in queries] == ["SELECT 1"]


def test_line_per_query_log_without_semicolons() -> None:
    text = "SELECT 1 FROM a\nSELECT 2 FROM b\n"
    assert len(parse_queries(text)) == 2


def test_empty_input_gives_no_queries() -> None:
    assert parse_queries("  \n -- nothing\n") == []


def test_read_queries_from_file(tmp_path: Path) -> None:
    path = tmp_path / "q.sql"
    path.write_text("SELECT 1;\nSELECT 2;", encoding="utf-8")
    assert len(read_queries(path)) == 2


def test_read_queries_missing_file(tmp_path: Path) -> None:
    with pytest.raises(QueryDoctorError, match="not found"):
        read_queries(tmp_path / "missing.sql")


def test_read_queries_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.sql"
    path.write_text("-- nothing", encoding="utf-8")
    with pytest.raises(QueryDoctorError, match="No queries"):
        read_queries(path)

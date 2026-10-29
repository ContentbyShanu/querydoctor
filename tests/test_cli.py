from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from querydoctor import __version__
from querydoctor.cli import app

runner = CliRunner()
SQL = "SELECT id, total_cents FROM orders WHERE user_id = 3 ORDER BY created_at DESC LIMIT 20"


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_seed_creates_database(tmp_path: Path) -> None:
    target = tmp_path / "x" / "shop.db"
    result = runner.invoke(app, ["seed", "--db", str(target), "--scale", "0.005"])
    assert result.exit_code == 0, result.output
    assert target.exists()
    assert "Created" in result.output


def test_schema_command(env_paths: dict[str, Path]) -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert "orders" in result.output and "order_items" in result.output


def test_schema_with_missing_database(tmp_path: Path) -> None:
    result = runner.invoke(app, ["schema", "--db", str(tmp_path / "no.db")])
    assert result.exit_code == 1
    assert "querydoctor seed" in result.output


def test_analyze_writes_report_and_migration(env_paths: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "migrations" / "001.sql"
    result = runner.invoke(app, ["analyze", SQL, "--migration", str(out)])
    assert result.exit_code == 0, result.output
    assert env_paths["report"].exists()
    assert out.exists() and "QueryDoctor migration" in out.read_text()


def test_analyze_from_file_and_json_output(env_paths: dict[str, Path], tmp_path: Path) -> None:
    sql_file = tmp_path / "q.sql"
    sql_file.write_text(f"-- name: Mine\n{SQL};\nSELECT 1;", encoding="utf-8")
    json_out = tmp_path / "out.json"
    result = runner.invoke(app, ["analyze", "--file", str(sql_file), "--json", str(json_out)])
    assert result.exit_code == 0, result.output
    data = json.loads(json_out.read_text())
    assert data["queries"][0]["title"] == "Mine"
    assert len(data["queries"]) == 2


def test_analyze_needs_a_query(env_paths: dict[str, Path]) -> None:
    result = runner.invoke(app, ["analyze"])
    assert result.exit_code == 1
    assert "Pass a query" in result.output


def test_analyze_missing_file(env_paths: dict[str, Path], tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", "--file", str(tmp_path / "missing.sql")])
    assert result.exit_code == 1


def test_analyze_missing_database(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", SQL, "--db", str(tmp_path / "no.db")])
    assert result.exit_code == 1
    assert "Database not found" in result.output


def test_analyze_shows_errors_for_bad_sql(env_paths: dict[str, Path]) -> None:
    result = runner.invoke(app, ["analyze", "DROP TABLE orders"])
    assert result.exit_code == 0
    assert "error" in result.output.lower()


@pytest.mark.parametrize("fmt", ["text", "markdown", "sql", "rollback", "json"])
def test_report_formats(env_paths: dict[str, Path], fmt: str) -> None:
    assert runner.invoke(app, ["analyze", SQL]).exit_code == 0
    result = runner.invoke(app, ["report", "--format", fmt])
    assert result.exit_code == 0, result.output
    assert result.output.strip()


def test_report_unknown_format(env_paths: dict[str, Path]) -> None:
    runner.invoke(app, ["analyze", SQL])
    result = runner.invoke(app, ["report", "--format", "pdf"])
    assert result.exit_code == 1
    assert "Unknown format" in result.output


def test_report_without_saved_analysis(env_paths: dict[str, Path]) -> None:
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 1
    assert "No saved report" in result.output


def test_bench_writes_docs(env_paths: dict[str, Path]) -> None:
    result = runner.invoke(app, ["bench"])
    assert result.exit_code == 0, result.output
    assert "Headline" in env_paths["bench_md"].read_text()
    assert json.loads(env_paths["bench_json"].read_text())["environment"]["sqlite"]


def test_bench_without_writing(env_paths: dict[str, Path]) -> None:
    result = runner.invoke(app, ["bench", "--no-write"])
    assert result.exit_code == 0
    assert not env_paths["bench_json"].exists()


def test_bench_missing_database(tmp_path: Path) -> None:
    assert runner.invoke(app, ["bench", "--db", str(tmp_path / "no.db")]).exit_code == 1


def test_serve_starts_uvicorn(env_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "uvicorn.run", lambda application, **kw: captured.update(kw, app=application)
    )
    result = runner.invoke(app, ["serve", "--port", "9123", "--host", "0.0.0.0"])
    assert result.exit_code == 0
    assert captured["port"] == 9123
    assert captured["host"] == "0.0.0.0"
    assert "9123" in result.output

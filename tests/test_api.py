from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from querydoctor.api import MAX_QUERIES, create_app
from querydoctor.bench import BenchResult
from querydoctor.config import Settings
from querydoctor.reporting import save_json
from querydoctor.web import STATIC_DIR, render_shell


def make_client(tmp_path: Path, db: Path) -> TestClient:
    settings = Settings(
        db_path=db,
        report_path=tmp_path / "r.json",
        bench_json=tmp_path / "bench.json",
        bench_md=tmp_path / "bench.md",
    )
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path: Path, small_db: Path) -> TestClient:
    return make_client(tmp_path, small_db)


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database_ready"] is True


def test_health_without_database(tmp_path: Path) -> None:
    body = make_client(tmp_path, tmp_path / "none.db").get("/api/health").json()
    assert body["database_ready"] is False


def test_dashboard_shell_loads_assets(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "/static/app.js" in page.text
    assert page.text == render_shell()


ROOT = Path(__file__).resolve().parents[1]


def test_only_the_pages_demo_ships_html() -> None:
    assert not list(STATIC_DIR.rglob("*.html"))
    skipped = {"site-packages", "node_modules", "build", "dist"}
    tracked = [
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*.html")
        if not any(part.startswith(".") or part in skipped for part in p.relative_to(ROOT).parts)
    ]
    assert tracked == ["index.html"]


def test_pages_demo_points_at_real_assets() -> None:
    page = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "QUERYDOCTOR_STATIC = true" in page
    assert (ROOT / ".nojekyll").exists()
    for ref in re.findall(r'(?:src|href)="(src/[^"]+)"', page):
        assert (ROOT / ref).exists(), ref
    assert (ROOT / "docs" / "benchmarks.json").exists()


def test_live_shell_is_not_in_demo_mode(client: TestClient) -> None:
    assert "QUERYDOCTOR_STATIC" not in client.get("/").text


def test_static_assets_are_served(client: TestClient) -> None:
    for name in ("app.js", "styles.css", "views/report.js", "favicon.svg"):
        assert client.get(f"/static/{name}").status_code == 200
    assert "javascript" in client.get("/static/app.js").headers["content-type"]


def test_schema(client: TestClient) -> None:
    tables = client.get("/api/schema").json()
    assert {t["name"] for t in tables} >= {"orders", "users"}


def test_schema_without_database(tmp_path: Path) -> None:
    response = make_client(tmp_path, tmp_path / "none.db").get("/api/schema")
    assert response.status_code == 409
    assert "querydoctor seed" in response.json()["detail"]


def test_samples(client: TestClient) -> None:
    samples = client.get("/api/samples").json()
    assert len(samples) == 10
    assert all(s["sql"].upper().startswith("SELECT") for s in samples)


def test_benchmarks_missing_then_present(
    tmp_path: Path, small_db: Path, bench_result: BenchResult
) -> None:
    client = make_client(tmp_path, small_db)
    assert client.get("/api/benchmarks").status_code == 404
    save_json(bench_result, tmp_path / "bench.json")
    body = client.get("/api/benchmarks").json()
    assert len(body["report"]["queries"]) == 10
    assert body["environment"]["sqlite"]


def test_analyze_returns_a_report(client: TestClient) -> None:
    sql = "-- name: Slow one\nSELECT id FROM orders WHERE user_id = 3 ORDER BY created_at;"
    response = client.post("/api/analyze", json={"sql": sql})
    assert response.status_code == 200
    body = response.json()
    assert body["queries"][0]["title"] == "Slow one"
    assert body["queries"][0]["status"] in {"optimized", "already_fast", "no_improvement"}
    assert "migration_sql" in body


def test_analyze_rejects_writes(client: TestClient) -> None:
    response = client.post("/api/analyze", json={"sql": "DELETE FROM orders"})
    assert response.status_code == 400


def test_analyze_rejects_empty_and_oversized_input(client: TestClient) -> None:
    assert client.post("/api/analyze", json={"sql": "-- nothing"}).status_code == 422
    assert client.post("/api/analyze", json={"sql": ""}).status_code == 422
    many = ";".join(f"SELECT {i}" for i in range(MAX_QUERIES + 1))
    assert client.post("/api/analyze", json={"sql": many}).status_code == 422


def test_analyze_without_database(tmp_path: Path) -> None:
    client = make_client(tmp_path, tmp_path / "none.db")
    assert client.post("/api/analyze", json={"sql": "SELECT 1"}).status_code == 409


def test_analyze_is_rejected_while_another_run_is_active(client: TestClient) -> None:
    busy = client.app.state.busy  # type: ignore[attr-defined]
    assert busy.acquire(blocking=False)
    try:
        response = client.post("/api/analyze", json={"sql": "SELECT 1"})
        assert response.status_code == 429
    finally:
        busy.release()
    assert client.post("/api/analyze", json={"sql": "SELECT 1"}).status_code == 200

"""REST API and dashboard host."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from querydoctor import __version__
from querydoctor.advisor import AdvisorConfig, analyze, describe_schema
from querydoctor.bench import BENCH_QUERIES
from querydoctor.config import Settings, get_settings
from querydoctor.errors import QueryDoctorError
from querydoctor.ingest import parse_queries
from querydoctor.models import FullReport, TableInfo
from querydoctor.safety import validate_readonly
from querydoctor.web import STATIC_DIR, render_shell

MAX_QUERIES = 10
MAX_SQL_CHARS = 20_000


class AnalyzeRequest(BaseModel):
    """Body of ``POST /api/analyze``."""

    sql: Annotated[str, Field(min_length=1, max_length=MAX_SQL_CHARS)]


class Health(BaseModel):
    """Body of ``GET /api/health``."""

    status: str
    version: str
    sqlite_version: str
    database_ready: bool


class Sample(BaseModel):
    """A ready-made query for the dashboard."""

    id: str
    title: str
    sql: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application."""
    cfg = settings or get_settings()
    app = FastAPI(title="QueryDoctor", version=__version__, docs_url="/api/docs", redoc_url=None)
    busy = threading.Lock()
    app.state.busy = busy

    def require_db() -> Path:
        if not cfg.db_path.exists():
            raise HTTPException(
                status_code=409,
                detail=f"Database not found at {cfg.db_path}. Run `querydoctor seed` first.",
            )
        return cfg.db_path

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return render_shell()

    @app.get("/api/health")
    def health() -> Health:
        return Health(
            status="ok",
            version=__version__,
            sqlite_version=sqlite3.sqlite_version,
            database_ready=cfg.db_path.exists(),
        )

    @app.get("/api/schema")
    def schema() -> list[TableInfo]:
        try:
            return describe_schema(require_db())
        except QueryDoctorError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/samples")
    def samples() -> list[Sample]:
        return [Sample(id=q.id, title=q.title, sql=q.sql) for q in BENCH_QUERIES]

    @app.get("/api/benchmarks")
    def benchmarks() -> dict[str, object]:
        if not cfg.bench_json.exists():
            raise HTTPException(
                status_code=404, detail="No benchmark results yet. Run `querydoctor bench`."
            )
        data: dict[str, object] = json.loads(cfg.bench_json.read_text(encoding="utf-8"))
        return data

    @app.post("/api/analyze")
    def analyze_endpoint(body: AnalyzeRequest) -> FullReport:
        db = require_db()
        queries = parse_queries(body.sql)
        if not queries:
            raise HTTPException(status_code=422, detail="No SQL statements found.")
        if len(queries) > MAX_QUERIES:
            raise HTTPException(status_code=422, detail=f"At most {MAX_QUERIES} queries at once.")
        for item in queries:
            try:
                validate_readonly(item.sql)
            except QueryDoctorError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not busy.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Another analysis is still running.")
        try:
            return analyze(db, queries, AdvisorConfig())
        except QueryDoctorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            busy.release()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()

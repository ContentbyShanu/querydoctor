"""Runtime configuration, read from environment variables with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    """Settings shared by the CLI and the web API."""

    db_path: Path = field(default_factory=lambda: _env_path("QUERYDOCTOR_DB", "data/shop.db"))
    host: str = field(default_factory=lambda: os.environ.get("QUERYDOCTOR_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("QUERYDOCTOR_PORT", "8000")))
    report_path: Path = field(
        default_factory=lambda: _env_path("QUERYDOCTOR_REPORT", ".querydoctor/last_report.json")
    )
    bench_json: Path = field(
        default_factory=lambda: _env_path("QUERYDOCTOR_BENCH_JSON", "docs/benchmarks.json")
    )
    bench_md: Path = field(
        default_factory=lambda: _env_path("QUERYDOCTOR_BENCH_MD", "docs/benchmarks.md")
    )


def get_settings() -> Settings:
    """Return settings resolved from the current environment."""
    return Settings()

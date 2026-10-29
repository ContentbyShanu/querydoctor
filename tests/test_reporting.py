from __future__ import annotations

from pathlib import Path

import pytest

from querydoctor.bench import BenchResult
from querydoctor.errors import QueryDoctorError
from querydoctor.models import FullReport
from querydoctor.reporting import (
    load_report,
    render_bench_markdown,
    render_markdown,
    save_json,
)


def test_json_round_trip(tmp_path: Path, sample_report: FullReport) -> None:
    path = tmp_path / "nested" / "r.json"
    save_json(sample_report, path)
    assert load_report(path) == sample_report


def test_load_missing_report(tmp_path: Path) -> None:
    with pytest.raises(QueryDoctorError, match="analyze"):
        load_report(tmp_path / "none.json")


def test_markdown_report_contains_the_essentials(sample_report: FullReport) -> None:
    text = render_markdown(sample_report)
    assert text.startswith("# QueryDoctor report")
    assert "CREATE INDEX" in text
    assert "## Migration" in text and "## Rollback" in text


def test_markdown_report_handles_errors(small_db: Path) -> None:
    from querydoctor.advisor import AdvisorConfig, analyze
    from querydoctor.ingest import QueryInput

    broken = analyze(small_db, [QueryInput(id="x", sql="DROP TABLE orders")], AdvisorConfig())
    assert "Could not analyze" in render_markdown(broken)


def test_bench_markdown(bench_result: BenchResult) -> None:
    text = render_bench_markdown(bench_result)
    assert "Headline" in text
    assert "| Query | Before | After | Speedup |" in text
    assert "querydoctor bench" in text
    assert len(bench_result.report.queries) == 10

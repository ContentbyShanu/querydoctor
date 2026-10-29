"""Migration script generation."""

from __future__ import annotations

from datetime import UTC, datetime

from querydoctor.formatting import fmt_bytes, fmt_ms, fmt_speedup
from querydoctor.models import QueryReport, Recommendation


def _if_not_exists(sql: str) -> str:
    return sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)


def unique_recommendations(reports: list[QueryReport]) -> list[tuple[Recommendation, list[str]]]:
    """Recommendations across queries, de-duplicated by index name with the queries they help."""
    merged: dict[str, tuple[Recommendation, list[str]]] = {}
    for report in reports:
        label = report.title or report.id
        for rec in report.recommendations:
            name = rec.candidate.name
            if name in merged:
                best, labels = merged[name]
                labels.append(label)
                if rec.speedup > best.speedup:
                    merged[name] = (rec, labels)
            else:
                merged[name] = (rec, [label])
    return list(merged.values())


def build_migration(reports: list[QueryReport]) -> tuple[str, str]:
    """Return ``(up_sql, down_sql)`` scripts for every validated recommendation."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    up = [
        f"-- QueryDoctor migration, generated {stamp}",
        "-- Every index below was validated on a sandbox copy of the database.",
        "-- Review, then run inside your normal deployment process.",
        "",
    ]
    down = [f"-- QueryDoctor rollback, generated {stamp}", ""]
    for rec, labels in unique_recommendations(reports):
        up.append(
            f"-- {', '.join(labels)}: {fmt_ms(rec.baseline_ms)} to {fmt_ms(rec.after_ms)} "
            f"({fmt_speedup(rec.speedup)}), +{fmt_bytes(rec.size_bytes)}, "
            f"confidence {rec.confidence}"
        )
        up.append(_if_not_exists(rec.create_sql) + ";")
        up.append("")
        down.append(rec.rollback_sql + ";")
    if len(up) == 4:
        up.append("-- No index changes recommended.")
    return "\n".join(up).rstrip() + "\n", "\n".join(down).rstrip() + "\n"

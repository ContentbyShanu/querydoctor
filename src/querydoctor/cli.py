"""Command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from querydoctor import __version__
from querydoctor.advisor import AdvisorConfig, analyze, describe_schema
from querydoctor.bench import run_bench
from querydoctor.config import get_settings
from querydoctor.errors import QueryDoctorError
from querydoctor.formatting import fmt_bytes, fmt_ms, fmt_percent, fmt_speedup
from querydoctor.ingest import QueryInput, parse_queries, read_queries
from querydoctor.models import FullReport
from querydoctor.reporting import (
    load_report,
    render_bench_markdown,
    render_markdown,
    save_json,
)
from querydoctor.seed import seed_database

app = typer.Typer(
    help="QueryDoctor: an index advisor that proves its recommendations.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err = Console(stderr=True)

DbOption = Annotated[
    Path | None, typer.Option("--db", help="SQLite database file (default: data/shop.db).")
]


def _db(path: Path | None) -> Path:
    return path or get_settings().db_path


def _fail(exc: Exception) -> typer.Exit:
    err.print(f"[bold red]Error:[/] {exc}")
    return typer.Exit(code=1)


def _print_report(report: FullReport) -> None:
    for q in report.queries:
        title = q.title or q.id
        if q.status == "error":
            console.print(Panel(q.message, title=f"{title}: error", border_style="red"))
            continue
        color = {"optimized": "green", "already_fast": "cyan", "no_improvement": "yellow"}[q.status]
        console.print(Panel(q.sql, title=title, border_style=color, title_align="left"))
        console.print(f"  {q.message}")
        if q.recommendations:
            table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
            for col in ("#", "Index", "Before", "After", "Gain", "Size", "Inserts", "Trust"):
                table.add_column(col)
            for r in q.recommendations:
                write = fmt_percent(r.write_overhead) if r.write_overhead is not None else "n/a"
                table.add_row(
                    str(r.rank),
                    r.create_sql,
                    fmt_ms(r.baseline_ms),
                    fmt_ms(r.after_ms),
                    fmt_speedup(r.speedup),
                    fmt_bytes(r.size_bytes),
                    f"+{write}",
                    r.confidence,
                )
            console.print(table)
            for r in q.recommendations:
                console.print(f"  [dim]{r.rank}. {r.explanation}[/]")
        console.print()
    console.print(f"[bold green]{report.headline}[/]")


@app.command()
def seed(
    db: DbOption = None,
    scale: Annotated[float, typer.Option(help="1.0 is about one million rows.")] = 1.0,
    seed_value: Annotated[int, typer.Option("--seed", help="Random seed.")] = 42,
) -> None:
    """Create a deterministic e-commerce database full of slow queries."""
    path = _db(db)
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        tasks: dict[str, TaskID] = {}

        def on_progress(table: str, done: int, total: int) -> None:
            if table not in tasks:
                tasks[table] = progress.add_task(f"Seeding {table}", total=total)
            progress.update(tasks[table], completed=done)

        try:
            counts = seed_database(path, scale=scale, seed=seed_value, progress=on_progress)
        except OSError as exc:
            raise _fail(exc) from exc
    console.print(
        f"[green]Created {path}[/] with {sum(counts.values()):,} rows "
        f"({fmt_bytes(path.stat().st_size)})."
    )


@app.command(name="analyze")
def analyze_cmd(
    sql: Annotated[str | None, typer.Argument(help="A SELECT query to analyze.")] = None,
    file: Annotated[Path | None, typer.Option("--file", "-f", help="A .sql or query log.")] = None,
    db: DbOption = None,
    migration: Annotated[Path | None, typer.Option(help="Write the migration SQL here.")] = None,
    json_out: Annotated[Path | None, typer.Option("--json", help="Also write the JSON.")] = None,
    max_rounds: Annotated[int, typer.Option(help="Max indexes recommended per query.")] = 3,
) -> None:
    """Analyze slow queries and recommend validated indexes."""
    settings = get_settings()
    try:
        queries: list[QueryInput] = []
        if file:
            queries += read_queries(file)
        if sql:
            queries += parse_queries(sql)
        if not queries:
            raise QueryDoctorError("Pass a query, or use --file queries.sql.")
        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console
        ) as progress:
            task = progress.add_task("Preparing sandbox", total=None)

            def on_progress(i: int, total: int, label: str) -> None:
                progress.update(task, description=f"Testing [{i}/{total}] {label}")

            report = analyze(_db(db), queries, AdvisorConfig(max_rounds=max_rounds), on_progress)
    except QueryDoctorError as exc:
        raise _fail(exc) from exc
    save_json(report, settings.report_path)
    if json_out:
        save_json(report, json_out)
    if migration:
        migration.parent.mkdir(parents=True, exist_ok=True)
        migration.write_text(report.migration_sql, encoding="utf-8")
        console.print(f"Migration written to {migration}")
    _print_report(report)


@app.command()
def report(
    fmt: Annotated[
        str, typer.Option("--format", help="text, markdown, sql, rollback or json.")
    ] = "text",
    source: Annotated[Path | None, typer.Option("--input", help="Saved report JSON.")] = None,
) -> None:
    """Show the most recent analysis again."""
    try:
        data = load_report(source or get_settings().report_path)
    except QueryDoctorError as exc:
        raise _fail(exc) from exc
    if fmt == "text":
        _print_report(data)
    elif fmt == "markdown":
        typer.echo(render_markdown(data))
    elif fmt == "sql":
        typer.echo(data.migration_sql)
    elif fmt == "rollback":
        typer.echo(data.rollback_sql)
    elif fmt == "json":
        typer.echo(data.model_dump_json(indent=2))
    else:
        raise _fail(QueryDoctorError(f"Unknown format: {fmt}"))


@app.command()
def bench(
    db: DbOption = None,
    write: Annotated[bool, typer.Option(help="Write docs/benchmarks.md and .json.")] = True,
) -> None:
    """Run the 10-query benchmark suite and publish the measured results."""
    settings = get_settings()
    try:
        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console
        ) as progress:
            task = progress.add_task("Preparing sandbox", total=None)

            def on_progress(i: int, total: int, label: str) -> None:
                progress.update(task, description=f"Benchmark [{i}/{total}] {label}")

            result = run_bench(_db(db), progress=on_progress)
    except QueryDoctorError as exc:
        raise _fail(exc) from exc
    _print_report(result.report)
    if write:
        save_json(result, settings.bench_json)
        settings.bench_md.parent.mkdir(parents=True, exist_ok=True)
        settings.bench_md.write_text(render_bench_markdown(result), encoding="utf-8")
        console.print(f"Wrote {settings.bench_md} and {settings.bench_json}")


@app.command()
def schema(db: DbOption = None) -> None:
    """List tables, row counts and existing indexes."""
    try:
        tables = describe_schema(_db(db))
    except QueryDoctorError as exc:
        raise _fail(exc) from exc
    table = Table(header_style="bold")
    for col in ("Table", "Rows", "Columns", "Indexes"):
        table.add_column(col)
    for t in tables:
        table.add_row(t.name, f"{t.rows:,}", ", ".join(t.columns), ", ".join(t.indexes) or "none")
    console.print(table)


@app.command()
def serve(
    db: DbOption = None,
    host: Annotated[str | None, typer.Option(help="Interface to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to listen on.")] = None,
) -> None:
    """Start the web dashboard and REST API."""
    import uvicorn

    from querydoctor.api import create_app
    from querydoctor.config import Settings

    base = get_settings()
    settings = Settings(
        db_path=_db(db),
        host=host or base.host,
        port=port or base.port,
        report_path=base.report_path,
        bench_json=base.bench_json,
        bench_md=base.bench_md,
    )
    console.print(f"Dashboard: [bold]http://{settings.host}:{settings.port}[/]")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)

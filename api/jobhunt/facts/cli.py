"""jobhunt facts: benchmark, decide, and backfill."""

from pathlib import Path

import typer

facts_app = typer.Typer(no_args_is_help=True, help="Job detail parsers.")


@facts_app.command("bench")
def bench(sample: int | None = typer.Option(None, "--sample", help="Stratified row cap.")) -> None:
    """Score default, gliner, and default+gliner. Writes api/reports/facts_bench_*."""
    from jobhunt.core.db import pool
    from jobhunt.facts.bench import run_bench

    conn = pool().getconn()
    try:
        path = run_bench(conn, sample=sample)
    finally:
        pool().putconn(conn)
    typer.echo(path)


_REPORT = typer.Argument(..., help="facts_bench JSON from the bench command.")


@facts_app.command("decide")
def decide(report: Path = _REPORT) -> None:
    """Write config/facts.yaml from a bench report."""
    from jobhunt.facts.decide import write_config

    if not report.is_file():
        typer.echo(f"report not found: {report}", err=True)
        raise typer.Exit(code=1)
    typer.echo(write_config(report))


@facts_app.command("backfill")
def backfill(
    dry_run: bool = typer.Option(False, "--dry-run"),
    restore: bool = typer.Option(False, "--restore"),
) -> None:
    """Fill empty job columns. --restore copies jobs_facts_backup_20261011 back."""
    from jobhunt.core.db import pool
    from jobhunt.facts.backfill import run_backfill

    conn = pool().getconn()
    try:
        typer.echo(run_backfill(conn, dry_run=dry_run, restore=restore))
    finally:
        pool().putconn(conn)


@facts_app.command("coverage")
def coverage() -> None:
    """Print missing Job details per source."""
    from jobhunt.core.db import tx
    from jobhunt.facts.coverage import coverage_table

    with tx() as conn:
        typer.echo(coverage_table(conn))

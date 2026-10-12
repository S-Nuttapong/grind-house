"""Job record commands."""

import typer

jobs_app = typer.Typer(no_args_is_help=True, help="Job records.")


@jobs_app.command("coverage")
def coverage() -> None:
    """Print missing Job details per source."""
    from jobhunt.core.db import tx
    from jobhunt.facts.coverage import coverage_table

    with tx() as conn:
        typer.echo(coverage_table(conn))


@jobs_app.command("backfill-roles")
def backfill_roles() -> None:
    """Recompute role and industry from titles and stored source payloads."""
    from jobhunt.jobs.backfill import backfill_roles as run

    typer.echo(f"updated {run()} jobs")

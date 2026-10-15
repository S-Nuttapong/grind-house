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


@jobs_app.command("prune")
def prune(apply: bool = typer.Option(False, "--apply", help="Delete off-target jobs.")) -> None:
    """Print jobs outside the target. --apply promotes roles, then deletes."""
    from jobhunt.core.db import tx
    from jobhunt.scrape.repo import promote_into_target, prune_off_target, prune_plan, prune_preview

    with tx() as conn:
        if apply:
            promoted = promote_into_target(conn)
            deleted, protected, titles = prune_preview(conn)
            prune_off_target(conn)
        else:
            promoted, deleted, protected, titles = prune_plan(conn)
    typer.echo(f"promoted {promoted}")
    typer.echo(f"deleted {deleted}" if apply else f"would delete {deleted}")
    typer.echo(f"protected {protected}")
    for title in titles:
        typer.echo(f"  {title}")
    if not apply:
        typer.echo("dry-run; pass --apply to delete")


@jobs_app.command("backfill-roles")
def backfill_roles() -> None:
    """Recompute role and industry from titles and stored source payloads."""
    from jobhunt.jobs.backfill import backfill_roles as run

    typer.echo(f"updated {run()} jobs")

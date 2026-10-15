"""Scrape commands: seed, fetch, tick, details, and company review."""

import typer

from jobhunt.core.cli import not_yet

commands = typer.Typer()

companies_app = typer.Typer(no_args_is_help=True, help="Company review.")
details_app = typer.Typer(no_args_is_help=True, help="Job description queue.")


@commands.command("seed")
def seed() -> None:
    """Load companies and fetch scopes."""
    from jobhunt.scrape.seed import seed as load_seed

    companies, scopes = load_seed()
    typer.echo(f"seeded {companies} companies and {scopes} scopes")


@commands.command("scrape")
def scrape(
    scope: int | None = typer.Option(None, "--scope"),
    source: str | None = typer.Option(None, "--source"),
) -> None:
    """Run one fetch scope or every scope for a source."""
    from jobhunt.scrape.runner import scrape as run_scrape

    if scope is None and source is None:
        typer.echo("pass --scope or --source", err=True)
        raise typer.Exit(code=1)
    try:
        results = run_scrape(scope_id=scope, source_id=source)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if not results:
        typer.echo("no scopes matched", err=True)
        raise typer.Exit(code=1)
    for result in results:
        typer.echo(
            f"run {result.run_id} {result.status}: "
            f"fetched {result.fetched}, new {result.new_jobs}, "
            f"updated {result.updated}, closed {result.closed}"
        )


@commands.command("tick")
def tick() -> None:
    """Poll searches whose markets are due, then ATS scopes."""
    from jobhunt.scrape.tick import tick as run_tick

    ran = run_tick()
    typer.echo(f"tick finished, {ran} sources")


@details_app.command("backfill")
def details_backfill(source: str = typer.Option(..., "--source")) -> None:
    """Fill descriptions for open jobs that are still missing one."""
    from jobhunt.scrape.details import backfill_details

    try:
        result = backfill_details(source)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"requeued {result.requeued}, filled {result.filled}, "
        f"gone {result.gone}, still pending {result.pending}"
    )


@companies_app.command("detect")
def companies_detect() -> None:
    """Detect an ATS from each company's careers URL."""
    not_yet("companies detect")

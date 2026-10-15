"""Database command group and the helper every slice CLI uses."""

import typer

db_app = typer.Typer(no_args_is_help=True, help="Database migrations.")


def not_yet(command: str) -> None:
    typer.echo(f"{command} is not built yet")
    raise typer.Exit(code=1)


@db_app.command("migrate")
def db_migrate(direction: str = typer.Argument("up")) -> None:
    """Apply migrations with dbmate (``up``, ``down``, or ``drop``)."""
    from jobhunt.core.migrate import migrate

    try:
        migrate(direction)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if direction == "up":
        _sync_fx()


def _sync_fx() -> None:
    """Refresh rates after a migration. A down API keeps the seeded rows."""
    from jobhunt.core.db import tx
    from jobhunt.scrape.normalize.fx import sync_fx

    try:
        with tx() as conn:
            count = sync_fx(conn)
    except Exception as exc:
        typer.echo(f"fx sync failed: {exc}", err=True)
        return
    typer.echo(f"fx rates upserted: {count}")

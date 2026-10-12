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

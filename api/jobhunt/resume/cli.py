"""Resume commands: the worker, the kit sync, and the acceptance report."""

from pathlib import Path

import typer

from jobhunt.core.settings import Settings

resume_app = typer.Typer(no_args_is_help=True, help="Generate a one-page resume for a job.")


@resume_app.command("worker")
def resume_worker() -> None:
    """Claim queued resume runs. Wakes on NOTIFY and falls back to a 30 second wait."""
    from jobhunt.composition import COMPOSITION
    from jobhunt.resume.pipeline import ResumePipeline

    ResumePipeline(COMPOSITION).serve()


@resume_app.command("sync-kit")
def resume_sync_kit() -> None:
    """Copy the vault kit and the server skill into the directory the worker reads."""
    from jobhunt.resume.kit import sync_kit

    destination = sync_kit(Path(Settings().vault_bank_path))
    typer.echo(f"kit synced to {destination}")


@resume_app.command("check")
def resume_check(run: int = typer.Option(..., "--run")) -> None:
    """Print PASS or FAIL for one stored resume run."""
    from jobhunt.core.db import tx
    from jobhunt.resume.check import check_run

    with tx() as conn:
        checks = check_run(conn, run)
    failed = False
    for name, passed, detail in checks:
        mark = "PASS" if passed else "FAIL"
        typer.echo(f"{mark}  {name}: {detail}")
        failed = failed or not passed
    if failed:
        raise typer.Exit(code=1)

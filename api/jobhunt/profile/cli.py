"""Profile commands: the summary build and the brag-vault import."""

import typer

from jobhunt.core.cli import not_yet

profile_app = typer.Typer(no_args_is_help=True, help="Profile summary and vault import.")


@profile_app.command("build")
def profile_build() -> None:
    """Build a sanitized profile from the brag bank."""
    not_yet("profile build")


@profile_app.command("import")
def profile_import() -> None:
    """Read the brag-doc vault into the database. The vault is not modified."""
    from jobhunt.core.db import tx
    from jobhunt.core.settings import Settings
    from jobhunt.profile.import_bank import import_bank

    bank = Settings().vault_bank_path
    with tx() as conn:
        counts = import_bank(conn, bank)
    typer.echo(f"imported {counts['entries']} brag docs and {counts['resumes']} resumes")

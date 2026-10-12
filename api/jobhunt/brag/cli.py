"""Brag doc commands. The vault is read once and rewritten only with --write."""

import typer

brag_app = typer.Typer(no_args_is_help=True, help="Brag docs.")


@brag_app.command("migrate-vault")
def brag_docs_migrate_vault(
    write: bool = typer.Option(False, "--write", help="Rewrite the vault. Copies Entries/ first."),
) -> None:
    """Rewrite old brag-bank frontmatter once. Dry-run unless --write is set."""
    from jobhunt.brag.migrate_vault import migrate_vault
    from jobhunt.core.settings import Settings

    changes = migrate_vault(Settings().vault_bank_path, write=write)
    if not changes:
        typer.echo("no Entries directory")
        return
    for change in changes:
        typer.echo(f"{change.path.name}: {change.action} ({change.detail})")
    rewritten = sum(1 for change in changes if change.action == "rewrite")
    verb = "rewrote" if write else "would rewrite"
    typer.echo(f"{verb} {rewritten} of {len(changes)} files")

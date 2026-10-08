"""Command line for Job Hunt OS."""

from datetime import UTC, datetime
from typing import Any

import typer
from psycopg import Connection

app = typer.Typer(no_args_is_help=True, help="Collect, rank, and review software-engineering jobs.")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations.")
profile_app = typer.Typer(no_args_is_help=True, help="Profile summary and vault import.")
brag_app = typer.Typer(no_args_is_help=True, help="Brag docs.")
calibrate_app = typer.Typer(no_args_is_help=True, help="Score calibration.")
ops_app = typer.Typer(no_args_is_help=True, help="Local scheduling.")
companies_app = typer.Typer(no_args_is_help=True, help="Company review.")

app.add_typer(db_app, name="db")
app.add_typer(profile_app, name="profile")
app.add_typer(brag_app, name="brag-docs")
app.add_typer(calibrate_app, name="calibrate")
app.add_typer(ops_app, name="ops")
app.add_typer(companies_app, name="companies")
fit_app = typer.Typer(no_args_is_help=True, help="Job fit scoring.")
app.add_typer(fit_app, name="fit")


def _not_yet(command: str) -> None:
    typer.echo(f"{command} is not built yet")
    raise typer.Exit(code=1)


@db_app.command("migrate")
def db_migrate(direction: str = typer.Argument("up")) -> None:
    """Apply migrations with dbmate (``up``, ``down``, or ``drop``)."""
    from jobhunt.db.migrate import migrate

    try:
        migrate(direction)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command("seed")
def seed() -> None:
    """Load companies and fetch scopes."""
    from jobhunt.seed import seed as load_seed

    companies, scopes = load_seed()
    typer.echo(f"seeded {companies} companies and {scopes} scopes")


@app.command("scrape")
def scrape(
    scope: int | None = typer.Option(None, "--scope"),
    source: str | None = typer.Option(None, "--source"),
) -> None:
    """Run one fetch scope or every scope for a source."""
    from jobhunt.scrape import scrape as run_scrape

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


@app.command("doctor")
def doctor() -> None:
    """Check the database, migrations, and vault path."""
    from jobhunt.doctor import doctor as run_doctor

    problems, summary = run_doctor()
    typer.echo(summary)
    for problem in problems:
        typer.echo(problem, err=True)
    if problems:
        raise typer.Exit(code=1)


@app.command("tick")
def tick() -> None:
    """Run due fetch scopes."""
    _not_yet("tick")


@profile_app.command("build")
def profile_build() -> None:
    """Build a sanitized profile from the brag bank."""
    _not_yet("profile build")


@app.command("match")
def match() -> None:
    """Run hard filters and the prefilter."""
    _not_yet("match")


@calibrate_app.command("sample")
def calibrate_sample(n: int = typer.Option(40, "--n")) -> None:
    """Print a stratified sample of scored jobs."""
    _ = n
    _not_yet("calibrate sample")


@calibrate_app.command("report")
def calibrate_report() -> None:
    """Print band agreement and precision@10."""
    _not_yet("calibrate report")


@profile_app.command("import")
def profile_import() -> None:
    """Read the brag-doc vault into the database. The vault is not modified."""
    from jobhunt.db import tx
    from jobhunt.fit.import_bank import import_bank
    from jobhunt.settings import Settings

    bank = Settings().vault_bank_path
    with tx() as conn:
        counts = import_bank(conn, bank)
    typer.echo(f"imported {counts['entries']} brag docs and {counts['resumes']} resumes")


@brag_app.command("migrate-vault")
def brag_docs_migrate_vault(
    write: bool = typer.Option(False, "--write", help="Rewrite the vault. Copies Entries/ first."),
) -> None:
    """Rewrite old brag-bank frontmatter once. Dry-run unless --write is set."""
    from jobhunt.fit.migrate_vault import migrate_vault
    from jobhunt.settings import Settings

    changes = migrate_vault(Settings().vault_bank_path, write=write)
    if not changes:
        typer.echo("no Entries directory")
        return
    for change in changes:
        typer.echo(f"{change.path.name}: {change.action} ({change.detail})")
    rewritten = sum(1 for change in changes if change.action == "rewrite")
    verb = "rewrote" if write else "would rewrite"
    typer.echo(f"{verb} {rewritten} of {len(changes)} files")


@fit_app.command("run")
def fit_run(
    mode: str = typer.Option("bank", "--mode"),
    limit: int | None = typer.Option(None, "--limit"),
) -> None:
    """Score open jobs against the brag docs or the selected resume."""
    from jobhunt.db import tx
    from jobhunt.fit.registry import create
    from jobhunt.fit.runner import run_fit
    from jobhunt.fit.sources import SourceError

    started = datetime.now(UTC)
    model = create()
    try:
        with tx() as conn:
            result = run_fit(conn, model, mode, limit=limit)
            _remember_cli_run(conn, model.model_id, mode, result, started, error=None)
    except (SourceError, ValueError) as exc:
        _remember_cli_failure(model.model_id, mode, started, str(exc))
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"scored {result['scored']}, skipped {result['skipped']} ({model.model_id})")


def _remember_cli_run(
    conn: Connection[Any],
    model_id: str,
    mode: str,
    result: dict[str, int],
    started: datetime,
    error: str | None,
) -> None:
    from jobhunt.db import fit_repo

    fit_repo.record_finished_run(
        conn,
        {
            "schedule_id": fit_repo.schedule_id_for_mode(conn, mode),
            "mode": mode,
            "trigger": "manual",
            "model_id": model_id,
            "status": "failed" if error else "ok",
            "scored": result["scored"],
            "skipped": result["skipped"],
            "error": error,
            "idempotency_key": f"cli|{mode}|{started.isoformat()}",
            "started_at": started,
            "finished_at": datetime.now(UTC),
        },
    )


def _remember_cli_failure(model_id: str, mode: str, started: datetime, error: str) -> None:
    from jobhunt.db import tx

    with tx() as conn:
        _remember_cli_run(conn, model_id, mode, {"scored": 0, "skipped": 0}, started, error)


@fit_app.command("worker")
def fit_worker_cmd() -> None:
    """Score jobs in the background. Loads the model once and polls every minute."""
    from jobhunt.fit.registry import create
    from jobhunt.fit.worker import serve

    serve(create())


@fit_app.command("download-model")
def fit_download_model() -> None:
    """Cache the BGE model into ./.models for the Docker worker."""
    import os

    os.environ.setdefault("HF_HOME", os.path.join(os.getcwd(), ".models"))
    from jobhunt.fit.bge import load_encoder

    load_encoder(os.environ["HF_HOME"])
    typer.echo(f"model cached in {os.environ['HF_HOME']}")


@fit_app.command("score")
def fit_score(
    job: int = typer.Option(..., "--job"),
    mode: str = typer.Option("bank", "--mode"),
) -> None:
    """Print the fit of one job. For ad-hoc checks; the board reads stored scores."""
    from jobhunt.db import tx
    from jobhunt.fit.calibrate import tier
    from jobhunt.fit.keywords import compare
    from jobhunt.fit.registry import create
    from jobhunt.fit.sources import SourceError, resolve

    model = create()
    try:
        with tx() as conn:
            _source_hash, profile_text, _resume_id = resolve(conn, mode, model)
            row = conn.execute(
                "SELECT title, description_md FROM jobs WHERE id = %s", (job,)
            ).fetchone()
    except SourceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if row is None:
        typer.echo(f"no job {job}", err=True)
        raise typer.Exit(code=1)
    description = f"{row[0]}\n{row[1] or ''}"
    score = model.score(description, profile_text)
    matched, missing = compare(profile_text, description)
    typer.echo(f"{score}% {tier(score)}")
    typer.echo(f"matched: {', '.join(matched) or '-'}")
    typer.echo(f"missing: {', '.join(missing) or '-'}")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
) -> None:
    """Serve the local filter UI on 127.0.0.1:8765."""
    if host not in {"127.0.0.1", "0.0.0.0"}:
        typer.echo("refusing to bind a non-local host", err=True)
        raise typer.Exit(code=1)
    import uvicorn

    uvicorn.run("jobhunt.web.app:create_app", factory=True, host=host, port=port)


@app.command("mcp")
def mcp() -> None:
    """Start the stdio MCP server."""
    _not_yet("mcp")


@app.command("stats")
def stats() -> None:
    """Print counts per source, stage, and band."""
    _not_yet("stats")


@ops_app.command("install-launchd")
def install_launchd(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Install the hourly launchd job."""
    _ = dry_run
    _not_yet("ops install-launchd")


@ops_app.command("uninstall-launchd")
def uninstall_launchd() -> None:
    """Remove the hourly launchd job."""
    _not_yet("ops uninstall-launchd")


@companies_app.command("detect")
def companies_detect() -> None:
    """Detect an ATS from each company's careers URL."""
    _not_yet("companies detect")


def main() -> None:
    app()

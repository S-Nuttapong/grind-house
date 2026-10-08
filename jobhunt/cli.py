"""Command line for Job Hunt OS."""

import typer

app = typer.Typer(no_args_is_help=True, help="Collect, rank, and review software-engineering jobs.")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations.")
profile_app = typer.Typer(no_args_is_help=True, help="Brag-bank profile.")
calibrate_app = typer.Typer(no_args_is_help=True, help="Score calibration.")
ops_app = typer.Typer(no_args_is_help=True, help="Local scheduling.")
companies_app = typer.Typer(no_args_is_help=True, help="Company review.")

app.add_typer(db_app, name="db")
app.add_typer(profile_app, name="profile")
app.add_typer(calibrate_app, name="calibrate")
app.add_typer(ops_app, name="ops")
app.add_typer(companies_app, name="companies")


def _not_yet(command: str) -> None:
    typer.echo(f"{command} is not built yet")
    raise typer.Exit(code=1)


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply migrations with dbmate."""
    _not_yet("db migrate")


@app.command("seed")
def seed() -> None:
    """Load companies and fetch scopes."""
    _not_yet("seed")


@app.command("scrape")
def scrape(
    scope: int | None = typer.Option(None, "--scope"),
    source: str | None = typer.Option(None, "--source"),
) -> None:
    """Run one fetch scope or every scope for a source."""
    _ = (scope, source)
    _not_yet("scrape")


@app.command("doctor")
def doctor() -> None:
    """Check the database, migrations, and vault path."""
    _not_yet("doctor")


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


@app.command("serve")
def serve() -> None:
    """Serve the local filter UI on 127.0.0.1:8765."""
    _not_yet("serve")


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

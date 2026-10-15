"""Command line for Job Hunt OS. Each slice owns its commands; this module composes them."""

import os
import subprocess
from pathlib import Path

import typer

from jobhunt.brag.cli import brag_app
from jobhunt.core.cli import db_app, not_yet
from jobhunt.facts.cli import facts_app
from jobhunt.fit.cli import calibrate_app, fit_app
from jobhunt.jobs.cli import jobs_app
from jobhunt.profile.cli import profile_app
from jobhunt.resume.cli import resume_app
from jobhunt.scrape.cli import commands as scrape_commands
from jobhunt.scrape.cli import companies_app, details_app

app = typer.Typer(no_args_is_help=True, help="Collect, rank, and review software-engineering jobs.")
ops_app = typer.Typer(no_args_is_help=True, help="Local scheduling.")

app.add_typer(db_app, name="db")
app.add_typer(profile_app, name="profile")
app.add_typer(brag_app, name="brag-docs")
app.add_typer(calibrate_app, name="calibrate")
app.add_typer(ops_app, name="ops")
app.add_typer(companies_app, name="companies")
app.add_typer(fit_app, name="fit")
app.add_typer(resume_app, name="resume")
app.add_typer(jobs_app, name="jobs")
app.add_typer(facts_app, name="facts")
app.add_typer(scrape_commands)
app.add_typer(details_app, name="details")


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


@app.command("match")
def match() -> None:
    """Run hard filters and the prefilter."""
    not_yet("match")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
) -> None:
    """Serve the local filter UI on 127.0.0.1:8765."""
    if host not in {"127.0.0.1", "0.0.0.0"}:
        typer.echo("refusing to bind a non-local host", err=True)
        raise typer.Exit(code=1)
    from jobhunt.workers import start

    start()
    import uvicorn

    uvicorn.run("jobhunt.app:create_app", factory=True, host=host, port=port)


@app.command("mcp")
def mcp() -> None:
    """Start the stdio MCP server."""
    not_yet("mcp")


@app.command("stats")
def stats() -> None:
    """Print counts per source, stage, and band."""
    not_yet("stats")


_LABEL = "com.san.jobhunt.tick"


def _plist() -> str:
    root = Path(__file__).resolve().parents[2]
    log_dir = Path.home() / "Library" / "Logs" / "jobhunt"
    command = f"cd {root}/api && op run --env-file=../.env.tpl -- uv run jobhunt tick"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{_LABEL}</string>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>RunAtLoad</key>
  <false/>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>{command}</string>
  </array>
  <key>StandardOutPath</key>
  <string>{log_dir}/tick.log</string>
  <key>StandardErrorPath</key>
  <string>{log_dir}/tick.log</string>
</dict>
</plist>
"""


@ops_app.command("install-launchd")
def install_launchd(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Install the 15-minute launchd job."""
    text = _plist()
    if dry_run:
        typer.echo(text)
        return
    path = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
    log_dir = Path.home() / "Library" / "Logs" / "jobhunt"
    log_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(path)], check=False)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    typer.echo(f"installed {path}")


@ops_app.command("uninstall-launchd")
def uninstall_launchd() -> None:
    """Remove the 15-minute launchd job."""
    path = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(path)], check=False)
    if path.exists():
        path.unlink()
    typer.echo(f"removed {path}")


def main() -> None:
    app()

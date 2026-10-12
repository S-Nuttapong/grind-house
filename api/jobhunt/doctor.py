"""Local health check: database, migrations, vault path, and size."""

from pathlib import Path

from jobhunt.core.db import tx
from jobhunt.core.log import redact
from jobhunt.core.settings import load_settings

_EXPECTED_MIGRATIONS = ("20261007000001", "20261007000002")


def doctor() -> tuple[list[str], str]:
    """Return problems and a size summary. An empty problem list is healthy."""
    settings = load_settings()
    summary = "database unread"
    try:
        with tx() as conn:
            conn.execute("SELECT 1")
            versions = {
                str(row[0])
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            size_row = conn.execute("SELECT pg_database_size(current_database())").fetchone()
            job_row = conn.execute("SELECT count(*) FROM jobs").fetchone()
    except Exception as exc:
        return [f"database unreachable: {redact(str(exc))}"], summary
    problems: list[str] = []
    missing = [version for version in _EXPECTED_MIGRATIONS if version not in versions]
    if missing:
        problems.append("migrations missing: " + ", ".join(missing))
    vault = Path(settings.vault_bank_path)
    if not vault.is_dir():
        problems.append(f"vault path is not a readable directory: {vault}")
    db_bytes = _as_int(size_row[0] if size_row else 0)
    job_count = _as_int(job_row[0] if job_row else 0)
    summary = f"{job_count} jobs, database {db_bytes} bytes, network: {_network()}"
    return problems, summary


def _network() -> str:
    """Corporate TLS is reported, not treated as a failed doctor check."""
    try:
        from jobhunt.scrape.network import corporate_network

        if corporate_network():
            return "corporate (scraping paused)"
    except Exception:
        return "unknown"
    return "personal"


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return int(str(value))
    return value

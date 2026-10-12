"""Shell out to dbmate. Never print the database URL."""

import os
import subprocess

from jobhunt.core.log import redact
from jobhunt.core.paths import migrations_dir


def migrate(direction: str = "up", database_url: str | None = None) -> None:
    """Run dbmate. ``direction`` is ``up``, ``down``, or ``drop``."""
    if direction not in {"up", "down", "drop"}:
        raise ValueError(f"unsupported migration direction: {direction}")
    env = os.environ.copy()
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    command = [
        "dbmate",
        "--no-dump-schema",
        "--migrations-dir",
        str(migrations_dir()),
        direction,
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        detail = redact(result.stderr or result.stdout or "dbmate failed")
        raise RuntimeError(detail)

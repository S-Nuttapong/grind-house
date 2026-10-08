"""Session database for integration tests.

Migrate once per session. Each test runs in a transaction that rolls back.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://jobhunt:jobhunt@127.0.0.1:54329/jobhunt_test?sslmode=disable",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("VAULT_BANK_PATH", "/tmp/jobhunt-synthetic-bank")


def _compose(*args: str) -> None:
    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", *args],
        cwd=ROOT,
        check=True,
    )


@pytest.fixture(scope="session")
def database_url() -> str:
    _compose("up", "-d", "--wait")
    from jobhunt.db.migrate import migrate

    migrate("drop", database_url=TEST_DATABASE_URL)
    migrate("up", database_url=TEST_DATABASE_URL)
    migrate("down", database_url=TEST_DATABASE_URL)
    migrate("up", database_url=TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.fixture
def committed(database_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A connection that commits for real. Used by code that commits mid-run.

    Cleans up everything the test inserted so later tests stay isolated.
    """
    # The worker reads through the pool, which may have been opened by an
    # earlier test before DATABASE_URL pointed here.
    from jobhunt.db import close_pool

    close_pool()
    connection = psycopg.connect(database_url)
    try:
        yield connection
    finally:
        close_pool()
        # Code under test commits, which ends this transaction, so read leftovers
        # through a fresh connection.
        connection.close()
        cleaner = psycopg.connect(database_url)
        for table in (
            "fit_run_events",
            "fit_runs",
            "job_fits",
            "fit_sources",
            "resumes",
            "brag_docs",
            "tags",
            "metric_keys",
            "postings",
            "jobs",
            "runs",
        ):
            cleaner.execute(f"DELETE FROM {table}")
        cleaner.execute("DELETE FROM fit_schedules WHERE name NOT LIKE '%daily%'")
        cleaner.execute("UPDATE bank_profile SET body_md = ''")
        cleaner.execute("UPDATE fit_worker SET model_id = NULL, heartbeat_at = NULL")
        cleaner.commit()
        cleaner.close()


@pytest.fixture
def conn(database_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    connection = psycopg.connect(database_url)
    connection.execute("BEGIN")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()

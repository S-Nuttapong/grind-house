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
def conn(database_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    connection = psycopg.connect(database_url)
    connection.execute("BEGIN")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()

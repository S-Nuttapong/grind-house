"""Connection pool, transactions, and a session-level advisory lock."""

from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg_pool import ConnectionPool

from jobhunt.core.settings import load_settings

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = load_settings().database_url.get_secret_value()
        # A tick holds the global lock plus one lock and one transaction per worker.
        # A full pool fails in 5 seconds instead of holding the request for the default 30.
        _pool = ConnectionPool(conninfo=url, min_size=1, max_size=16, timeout=5, open=True)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def tx() -> Iterator[Connection[tuple[object, ...]]]:
    with pool().connection() as connection:
        with connection.transaction():
            yield connection


@contextmanager
def advisory_lock(name: str) -> Iterator[bool]:
    """Hold ``pg_try_advisory_lock`` on a dedicated connection until exit."""
    connection = pool().getconn()
    acquired = False
    try:
        row = connection.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s))",
            (name,),
        ).fetchone()
        acquired = bool(row is not None and row[0])
        if acquired:
            connection.commit()
        yield acquired
    finally:
        if acquired:
            connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
            connection.commit()
        pool().putconn(connection)

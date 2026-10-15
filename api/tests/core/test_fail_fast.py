import time
from contextlib import contextmanager
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool, PoolTimeout

from jobhunt.app import create_app
from jobhunt.fit.base import FitRateLimited
from jobhunt.fit.runner import _score_all


def test_busy_database_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def busy() -> Iterator[None]:
        raise PoolTimeout("busy")
        yield

    monkeypatch.setattr("jobhunt.jobs.router.tx", busy)
    client = TestClient(create_app())
    started = time.monotonic()
    response = client.get("/api/facets")
    assert response.status_code == 503
    assert time.monotonic() - started < 6


def test_pool_gives_up_within_six_seconds(database_url: str) -> None:
    limited = ConnectionPool(conninfo=database_url, min_size=1, max_size=1, timeout=5, open=True)
    try:
        with limited.connection():
            started = time.monotonic()
            with pytest.raises(PoolTimeout):
                with limited.connection():
                    pass
            assert time.monotonic() - started < 6
    finally:
        limited.close()


def test_rate_limit_stops_the_batch() -> None:
    class Limited:
        model_id = "fake"

        def fit_many(self, docs: list[object], descriptions: list[str]) -> list[object]:
            raise FitRateLimited("429 plan limit")

    with pytest.raises(FitRateLimited):
        _score_all(Limited(), [], ["one", "two"])  # type: ignore[arg-type]

"""LinkedIn detail fetch: retry a short 429, and do not mark an empty page done."""

import httpx
import psycopg
import pytest
import respx
from jobhunt.core.db import tx
from jobhunt.core.http import HttpClient
from jobhunt.scrape import repo
from jobhunt.scrape.details import DetailDrain, backfill_details, drain_details

_MARKUP = (
    '<div class="show-more-less-html__markup"><p>Build the product.</p></div>'
    '<div class="description__job-criteria-item">'
    '<span class="description__job-criteria-subheader">Seniority level</span>'
    '<span class="description__job-criteria-text">Mid-Senior level</span>'
    "</div>"
)


def _client(slept: list[float]) -> HttpClient:
    return HttpClient(
        sleep=lambda seconds: slept.append(seconds),
        uniform=lambda _low, _high: 0.0,
        min_delay=0.0,
        max_delay=0.0,
    )


def _url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"


def _seed(
    source_job_ids: list[str],
    *,
    description: str | None = None,
    detail_status: str = "pending",
    attempts: int = 0,
    closed: bool = False,
    name: str = "linkedin-detail",
) -> tuple[int, list[tuple[int, int]]]:
    rows: list[tuple[int, int]] = []
    with tx() as conn:
        company_id = repo.insert_company(conn, name=name, name_norm=name)
        for index, source_job_id in enumerate(source_job_ids):
            job_id = repo.insert_job(
                conn,
                company_id=company_id,
                title="Software Engineer",
                title_norm=f"software engineer {source_job_id}",
                apply_url=f"https://www.linkedin.com/jobs/view/{source_job_id}",
                dedupe_key=f"{name}|{source_job_id}",
                description_md=description,
            )
            if closed:
                conn.execute("UPDATE jobs SET closed_at = now() WHERE id = %s", (job_id,))
            posting_id = repo.insert_posting(
                conn,
                job_id=job_id,
                source_id="linkedin_guest",
                source_job_id=source_job_id,
                source_url=f"https://www.linkedin.com/jobs/view/{source_job_id}",
                content_hash=source_job_id,
                detail_status=detail_status,
            )
            conn.execute(
                """
                UPDATE postings
                SET detail_attempts = %s,
                    first_seen_at = now() + %s * interval '1 second'
                WHERE id = %s
                """,
                (attempts, index, posting_id),
            )
            rows.append((posting_id, job_id))
    return company_id, rows


def _drop(company_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM jobs WHERE company_id = %s", (company_id,))
        conn.execute("DELETE FROM companies WHERE id = %s", (company_id,))


def _posting(posting_id: int) -> tuple[object, ...]:
    with tx() as conn:
        row = conn.execute(
            """
            SELECT p.detail_status, p.detail_attempts, coalesce(j.description_md, '')
            FROM postings p
            JOIN jobs j ON j.id = p.job_id
            WHERE p.id = %s
            """,
            (posting_id,),
        ).fetchone()
    assert row is not None
    return row


@respx.mock
def test_429_then_200_saves_the_description(committed: psycopg.Connection) -> None:
    _ = committed
    company_id, rows = _seed(["429200"])
    slept: list[float] = []
    respx.get(_url("429200")).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, text=_MARKUP)]
    )
    try:
        outcome = drain_details("linkedin_guest", _client(slept), limit=10)
        assert outcome.filled == 1
        assert outcome.stopped is None
        assert slept == [pytest.approx(2.5)]
        status, attempts, description = _posting(rows[0][0])
        assert status == "done"
        assert attempts == 1
        assert "Build the product" in str(description)
    finally:
        _drop(company_id)


@respx.mock
def test_429_five_times_stays_pending(committed: psycopg.Connection) -> None:
    _ = committed
    company_id, rows = _seed(["429x5"])
    respx.get(_url("429x5")).mock(return_value=httpx.Response(429))
    try:
        outcome = drain_details("linkedin_guest", _client([]), limit=10)
        assert outcome.deferred == 1
        assert outcome.stopped is None
        assert _posting(rows[0][0])[:2] == ("pending", 0)
    finally:
        _drop(company_id)


@respx.mock
def test_three_throttled_postings_stop_the_queue(committed: psycopg.Connection) -> None:
    _ = committed
    company_id, rows = _seed(["t1", "t2", "t3", "t4"])
    route = respx.get(url__regex=r".*/jobPosting/.*").mock(return_value=httpx.Response(429))
    try:
        outcome = drain_details("linkedin_guest", _client([]), limit=10)
        assert outcome.stopped == "throttled"
        assert outcome.deferred == 3
        assert route.call_count == 15
        for posting_id, _job_id in rows:
            assert _posting(posting_id)[:2] == ("pending", 0)
    finally:
        _drop(company_id)


@respx.mock
def test_404_marks_the_posting_gone(committed: psycopg.Connection) -> None:
    _ = committed
    company_id, rows = _seed(["gone1"])
    respx.get(_url("gone1")).mock(return_value=httpx.Response(404))
    try:
        outcome = drain_details("linkedin_guest", _client([]), limit=10)
        assert outcome.gone == 1
        assert _posting(rows[0][0])[:2] == ("gone", 1)
    finally:
        _drop(company_id)


@respx.mock
def test_empty_markup_counts_as_a_failed_attempt(committed: psycopg.Connection) -> None:
    _ = committed
    company_id, rows = _seed(["empty1"])
    respx.get(_url("empty1")).mock(return_value=httpx.Response(200, text="<html></html>"))
    try:
        outcome = drain_details("linkedin_guest", _client([]), limit=10)
        assert outcome.failed == 1
        assert outcome.filled == 0
        assert _posting(rows[0][0]) == ("pending", 1, "")
    finally:
        _drop(company_id)


@respx.mock
def test_999_stops_the_queue_immediately(committed: psycopg.Connection) -> None:
    _ = committed
    company_id, rows = _seed(["block1", "block2"])
    route = respx.get(url__regex=r".*/jobPosting/.*").mock(return_value=httpx.Response(999))
    try:
        outcome = drain_details("linkedin_guest", _client([]), limit=10)
        assert outcome.stopped == "blocked"
        # The shared client retries a 999 three times before the queue stops.
        assert route.call_count == 3
        assert _posting(rows[0][0])[:2] == ("pending", 0)
        assert _posting(rows[1][0])[:2] == ("pending", 0)
    finally:
        _drop(company_id)


@respx.mock
def test_one_network_error_then_200_saves(committed: psycopg.Connection) -> None:
    _ = committed
    company_id, rows = _seed(["net1"])
    # HttpClient already retries a transport error three times. The fourth
    # failure is the one fetch_detail retries once.
    respx.get(_url("net1")).mock(
        side_effect=[
            httpx.ConnectError("reset"),
            httpx.ConnectError("reset"),
            httpx.ConnectError("reset"),
            httpx.Response(200, text=_MARKUP),
        ]
    )
    try:
        outcome = drain_details("linkedin_guest", _client([]), limit=10)
        assert outcome.filled == 1
        assert "Build the product" in str(_posting(rows[0][0])[2])
    finally:
        _drop(company_id)


def test_requeue_only_open_jobs_missing_a_description(conn: psycopg.Connection) -> None:
    company_id = repo.insert_company(conn, name="requeue co", name_norm="requeue-co")

    def add(
        source_job_id: str,
        *,
        description: str | None,
        status: str,
        attempts: int,
        closed: bool = False,
    ) -> int:
        job_id = repo.insert_job(
            conn,
            company_id=company_id,
            title="Software Engineer",
            title_norm=f"software engineer {source_job_id}",
            apply_url=f"https://www.linkedin.com/jobs/view/{source_job_id}",
            dedupe_key=f"requeue|{source_job_id}",
            description_md=description,
        )
        if closed:
            conn.execute("UPDATE jobs SET closed_at = now() WHERE id = %s", (job_id,))
        posting_id = repo.insert_posting(
            conn,
            job_id=job_id,
            source_id="linkedin_guest",
            source_job_id=source_job_id,
            source_url=f"https://www.linkedin.com/jobs/view/{source_job_id}",
            content_hash=source_job_id,
            detail_status=status,
        )
        conn.execute(
            "UPDATE postings SET detail_attempts = %s WHERE id = %s",
            (attempts, posting_id),
        )
        return posting_id

    failed = add("rq-failed", description=None, status="failed", attempts=3)
    done_empty = add("rq-empty", description="", status="done", attempts=1)
    described = add("rq-full", description="Already filled.", status="done", attempts=1)
    closed = add("rq-closed", description=None, status="failed", attempts=3, closed=True)
    gone = add("rq-gone", description=None, status="gone", attempts=1)

    assert repo.requeue_missing_details(conn, "linkedin_guest") == 2

    def state(posting_id: int) -> tuple[object, object]:
        row = conn.execute(
            "SELECT detail_status, detail_attempts FROM postings WHERE id = %s",
            (posting_id,),
        ).fetchone()
        assert row is not None
        return (row[0], row[1])

    assert state(failed) == ("pending", 0)
    assert state(done_empty) == ("pending", 0)
    assert state(described) == ("done", 1)
    assert state(closed) == ("failed", 3)
    assert state(gone) == ("gone", 1)


def test_backfill_stops_when_the_queue_is_empty(
    committed: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = committed
    company_id, rows = _seed(
        ["bf-empty"],
        description="Kept.",
        detail_status="done",
        name="bf-empty",
    )
    calls: list[int] = []

    def fake_drain(source_id: str, http: HttpClient, *, limit: int | None = None) -> DetailDrain:
        _ = (source_id, http, limit)
        calls.append(1)
        return DetailDrain()

    monkeypatch.setattr("jobhunt.scrape.details.corporate_network", lambda: False)
    monkeypatch.setattr("jobhunt.scrape.tick._http", lambda _source: _client([]))
    monkeypatch.setattr("jobhunt.scrape.details.drain_details", fake_drain)
    try:
        result = backfill_details("linkedin_guest")
        assert calls == []
        assert result.requeued == 0
        assert result.pending == 0
        assert _posting(rows[0][0])[0] == "done"
    finally:
        _drop(company_id)


def test_backfill_stops_when_the_queue_is_blocked(
    committed: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = committed
    company_id, rows = _seed(["bf-block"], name="bf-block")
    calls: list[int] = []

    def fake_drain(source_id: str, http: HttpClient, *, limit: int | None = None) -> DetailDrain:
        _ = (source_id, http, limit)
        calls.append(1)
        return DetailDrain(stopped="blocked")

    monkeypatch.setattr("jobhunt.scrape.details.corporate_network", lambda: False)
    monkeypatch.setattr("jobhunt.scrape.tick._http", lambda _source: _client([]))
    monkeypatch.setattr("jobhunt.scrape.details.drain_details", fake_drain)
    try:
        result = backfill_details("linkedin_guest")
        assert calls == [1]
        assert result.requeued == 1
        assert result.filled == 0
        assert result.pending == 1
        assert _posting(rows[0][0])[:2] == ("pending", 0)
    finally:
        _drop(company_id)

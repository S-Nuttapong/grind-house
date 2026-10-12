"""Profile, resume, and schedule routes, plus the board reading stored fit scores."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from jobhunt.app import create_app
from jobhunt.brag import repo as brag_repo
from jobhunt.core.db import close_pool
from jobhunt.fit import repo as fit_repo
from jobhunt.fit.fake import FakeFitScorer
from jobhunt.fit.runner import run_fit
from jobhunt.profile.import_bank import import_bank
from jobhunt.scrape import repo


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    close_pool()
    with TestClient(create_app()) as test_client:
        yield test_client
    close_pool()
    with psycopg.connect(database_url) as conn:
        tables = (
            "fit_run_events",
            "fit_runs",
            "job_fits",
            "fit_sources",
            "resumes",
            "brag_docs",
            "tags",
            "metric_keys",
        )
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM fit_schedules WHERE name NOT LIKE '%daily%'")
        conn.execute("UPDATE bank_profile SET body_md = ''")
        conn.commit()


def test_summary_round_trip(client: TestClient) -> None:
    saved = client.put("/api/profile/summary", json={"body_md": "Timeline."})
    assert saved.json()["body_md"] == "Timeline."
    assert client.get("/api/profile/summary").json()["body_md"] == "Timeline."


def test_resume_upload_select_and_reject(client: TestClient) -> None:
    rejected = client.post(
        "/api/resumes", files={"file": ("notes.exe", b"nope", "application/octet-stream")}
    )
    assert rejected.status_code == 422

    uploaded = client.post(
        "/api/resumes", files={"file": ("resume.md", b"# Me\nGo, Kafka", "text/markdown")}
    )
    assert uploaded.status_code == 201
    resume_id = uploaded.json()["id"]
    assert "Kafka" in uploaded.json()["text"]

    assert client.post(f"/api/resumes/{resume_id}/select").json()["is_selected"] is True
    assert client.delete(f"/api/resumes/{resume_id}").status_code == 204
    assert client.delete(f"/api/resumes/{resume_id}").status_code == 404


def test_schedule_validation_and_queue(client: TestClient) -> None:
    bad = client.post(
        "/api/fit/schedules",
        json={"name": "Too fast", "mode": "bank", "cron": "*/5 * * * *"},
    )
    assert bad.status_code == 422
    assert "15" in bad.json()["detail"]

    created = client.post(
        "/api/fit/schedules",
        json={"name": "Nightly", "mode": "bank", "cron": "0 2 * * *", "timezone": "Asia/Bangkok"},
    )
    assert created.status_code == 201
    body = created.json()
    assert "02:00" in body["description"]
    assert len(body["upcoming"]) == 3

    schedule_id = body["id"]
    first = client.post(f"/api/fit/schedules/{schedule_id}/run")
    second = client.post(f"/api/fit/schedules/{schedule_id}/run")
    assert first.status_code == 202
    assert second.json()["created"] is False
    assert second.json()["run_id"] == first.json()["run_id"]

    assert client.delete(f"/api/fit/schedules/{schedule_id}").status_code == 204


def test_schedule_shows_last_run(client: TestClient, database_url: str) -> None:
    from datetime import UTC, datetime, timedelta

    created = client.post(
        "/api/fit/schedules",
        json={
            "name": "Nightly last",
            "mode": "bank",
            "cron": "0 2 * * *",
            "timezone": "Asia/Bangkok",
        },
    )
    schedule_id = created.json()["id"]
    started = datetime(2026, 10, 8, 7, 37, 20, tzinfo=UTC)
    with psycopg.connect(database_url) as conn:
        fit_repo.record_finished_run(
            conn,
            {
                "schedule_id": schedule_id,
                "mode": "bank",
                "trigger": "manual",
                "model_id": "fake/v1",
                "status": "ok",
                "scored": 5736,
                "skipped": 0,
                "error": None,
                "idempotency_key": "test-last-run",
                "started_at": started,
                "finished_at": started + timedelta(minutes=15, seconds=41),
            },
        )
        conn.commit()

    listed = client.get("/api/fit/schedules")
    row = next(item for item in listed.json() if item["id"] == schedule_id)
    assert row["last_run"]["scored"] == 5736
    assert row["last_run"]["status"] == "ok"
    assert row["last_run"]["started_at"].startswith("2026-10-08T07:37:20")

    later = started + timedelta(minutes=20)
    with psycopg.connect(database_url) as conn:
        fit_repo.record_finished_run(
            conn,
            {
                "schedule_id": None,
                "mode": "bank",
                "trigger": "manual",
                "model_id": "fake/v1",
                "status": "ok",
                "scored": 0,
                "skipped": 5736,
                "error": None,
                "idempotency_key": "test-last-run-skip",
                "started_at": later,
                "finished_at": later + timedelta(seconds=16),
            },
        )
        conn.commit()
    rows = client.get("/api/fit/schedules").json()
    again = next(item for item in rows if item["id"] == schedule_id)
    assert again["last_run"]["skipped"] == 5736
    assert client.delete(f"/api/fit/schedules/{schedule_id}").status_code == 204


def test_board_sorts_by_stored_score(client: TestClient, database_url: str, bank_dir: Path) -> None:
    with psycopg.connect(database_url) as conn:
        import_bank(conn, bank_dir)
        company_id = repo.insert_company(conn, name="Board Fit Co", name_norm="board fit co")
        weak = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzFit Designer",
            title_norm="zzfit designer",
            apply_url="https://example.com/fit-weak",
            dedupe_key=f"{company_id}|zzfit designer|SG",
            description_md="Brand design only.",
        )
        strong = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzFit Go Engineer",
            title_norm="zzfit go engineer",
            apply_url="https://example.com/fit-strong",
            dedupe_key=f"{company_id}|zzfit go|SG",
            description_md="Go and Kafka for payments.",
        )
        run_fit(conn, FakeFitScorer(), "bank")
        conn.commit()

    try:
        body = client.get("/api/jobs", params={"q": "ZzFit"}).json()
        assert [job["title"] for job in body["jobs"]] == ["ZzFit Go Engineer", "ZzFit Designer"]
        assert body["jobs"][0]["fit_tier"] == "strong"
        assert body["jobs"][0]["score"] > body["jobs"][1]["score"]

        high = client.get("/api/jobs", params={"q": "ZzFit", "min_score": "80"}).json()
        assert [job["id"] for job in high["jobs"]] == [strong]

        detail = client.get(f"/api/jobs/{strong}").json()
        assert "fintech" in detail["matched_terms"]
        assert detail["top_brags"][0]["id"] == "BB-001"
        assert detail["top_brags"][0]["title"] == "Shipped the payments service"
        assert detail["coverage"] == 1.0
        assert detail["gaps"] == []
        assert client.get(f"/api/jobs/{weak}").json()["fit_tier"] == "low"
    finally:
        with psycopg.connect(database_url) as conn:
            conn.execute("DELETE FROM jobs WHERE id = ANY(%s)", ([weak, strong],))
            conn.execute("DELETE FROM companies WHERE id = %s", (company_id,))
            conn.commit()


def test_stream_replays_then_follows(client: TestClient, database_url: str) -> None:
    import threading
    import time

    with psycopg.connect(database_url) as conn:
        run_id, _created = fit_repo.enqueue_run(
            conn,
            {
                "schedule_id": None,
                "mode": "bank",
                "trigger": "manual",
                "model_id": "fake/v1",
                "idempotency_key": "stream-test",
            },
        )
        first = fit_repo.add_run_event(conn, run_id, "progress", {"done": 1, "total": 2, "pct": 50})
        conn.commit()

    def emit_final() -> None:
        time.sleep(0.5)
        with psycopg.connect(database_url) as conn:
            event_id = fit_repo.add_run_event(conn, run_id, "status", {"status": "ok"})
            fit_repo.notify_run(conn, run_id, event_id)
            conn.commit()

    threading.Thread(target=emit_final, daemon=True).start()
    with client.stream("GET", f"/api/fit/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join(response.iter_text())
    assert f"id: {first}" in body
    assert '"status": "ok"' in body

    # A reconnect resumes after the last event it saw, without repeating it.
    with client.stream(
        "GET", f"/api/fit/runs/{run_id}/stream", headers={"Last-Event-ID": str(first)}
    ) as response:
        resumed = "".join(response.iter_text())
    assert f"id: {first}" not in resumed
    assert '"status": "ok"' in resumed


def test_status_reports_stale_after_an_edit(
    client: TestClient, database_url: str, bank_dir: Path
) -> None:
    with psycopg.connect(database_url) as conn:
        import_bank(conn, bank_dir)
        run_fit(conn, FakeFitScorer(), "bank")
        brag_repo.save_brag_doc(
            conn,
            {
                "id": "BB-777",
                "title": "New work",
                "date": date(2026, 10, 8),
                "company": None,
                "role": None,
                "description_md": "Added after scoring.",
                "origin": "ui",
                "tag_ids": [],
                "metrics": [],
                "attachments": [],
            },
        )
        conn.commit()
    status = client.get("/api/fit/status").json()
    assert status["modes"]["bank"]["stale"] is True

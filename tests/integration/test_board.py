"""The Indeed-style board lists jobs, filters them, and records save."""

from datetime import date, timedelta

import psycopg
from fastapi.testclient import TestClient
from jobhunt.db import close_pool, repo
from jobhunt.web.app import create_app


def test_board_lists_job_and_save_writes_event(database_url: str) -> None:
    close_pool()
    today = date.today()
    with psycopg.connect(database_url) as conn:
        company_id = repo.insert_company(conn, name="Board Co", name_norm="board co zz", tier="B")
        job_id = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzIndeed Board Engineer",
            title_norm="zzindeed board engineer",
            apply_url="https://example.com/board",
            dedupe_key=f"{company_id}|zzindeed board engineer|SG",
            country="SG",
            city="ZzTestville",
            salary_min=120000,
            salary_currency="USD",
            posted_at=today,
            description_md="Ships the board.\n\n<script>alert(1)</script>",
        )
        old_id = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzIndeed Old Role",
            title_norm="zzindeed old role",
            apply_url="https://example.com/old",
            dedupe_key=f"{company_id}|zzindeed old role|US",
            country="US",
            city="Otherplace",
            posted_at=today - timedelta(days=40),
            description_md="An older role.",
        )
        conn.commit()
    try:
        client = TestClient(create_app())
        page = client.get("/jobs", params={"q": "ZzIndeed"})
        assert page.status_code == 200
        assert "ZzIndeed Board Engineer" in page.text
        assert "Find jobs" in page.text
        assert "<script>alert" not in page.text

        saved = client.post(f"/jobs/{job_id}/events", data={"status": "saved"})
        assert saved.status_code == 200
        assert "saved" in saved.text
        assert saved.headers["hx-trigger"]

        partial = client.get("/jobs", params={"q": "ZzIndeed"}, headers={"HX-Request": "true"})
        assert partial.status_code == 200
        assert "ZzIndeed Board Engineer" in partial.text
        assert "<!DOCTYPE html>" not in partial.text

        located = client.get("/jobs", params={"q": "ZzIndeed", "where": "ZzTestville"})
        assert "ZzIndeed Board Engineer" in located.text
        assert "ZzIndeed Old Role" not in located.text

        recent = client.get("/jobs", params={"q": "ZzIndeed", "posted_within": "1"})
        assert "ZzIndeed Board Engineer" in recent.text
        assert "ZzIndeed Old Role" not in recent.text

        paid = client.get("/jobs", params={"q": "ZzIndeed", "has_salary": "1"})
        assert "120,000" in paid.text
        assert "ZzIndeed Old Role" not in paid.text

        selected = client.get("/", params={"jk": str(job_id)})
        assert "Full job description" in selected.text
        assert "Ships the board." in selected.text
        assert "&lt;script&gt;" in selected.text
        assert "<script>alert" not in selected.text

        direct = client.get(f"/jobs/{job_id}")
        assert direct.status_code == 200
        assert "<!DOCTYPE html>" in direct.text
        assert "Apply now" in direct.text
        assert "&lt;script&gt;" in direct.text
        assert "<script>alert" not in direct.text

        drawer = client.get(f"/jobs/{job_id}", headers={"HX-Request": "true"})
        assert "<!DOCTYPE html>" not in drawer.text
        assert "alert(1)" in drawer.text
        assert "&lt;script&gt;" in drawer.text
        assert "<script>alert" not in drawer.text
    finally:
        close_pool()
        with psycopg.connect(database_url) as conn:
            conn.execute("DELETE FROM jobs WHERE id = ANY(%s)", ([job_id, old_id],))
            conn.execute("DELETE FROM companies WHERE id = %s", (company_id,))
            conn.commit()

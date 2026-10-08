"""The board lists jobs and save/skip writes an event."""

import psycopg
from fastapi.testclient import TestClient
from jobhunt.db import close_pool, repo
from jobhunt.web.app import create_app


def test_board_lists_job_and_save_writes_event(database_url: str) -> None:
    close_pool()
    with psycopg.connect(database_url) as conn:
        company_id = repo.insert_company(conn, name="Board Co", name_norm="board co", tier="B")
        job_id = repo.insert_job(
            conn,
            company_id=company_id,
            title="Board Engineer",
            title_norm="board engineer",
            apply_url="https://example.com/board",
            dedupe_key=f"{company_id}|board engineer|SG",
            country="SG",
            description_md="Ships the local board.",
        )
        conn.commit()
    try:
        client = TestClient(create_app())
        page = client.get("/jobs")
        assert page.status_code == 200
        assert "Board Engineer" in page.text
        saved = client.post(f"/jobs/{job_id}/events", data={"status": "saved"})
        assert saved.status_code == 200
        assert "saved" in saved.text
        partial = client.get("/jobs", params={"q": "Board"}, headers={"HX-Request": "true"})
        assert partial.status_code == 200
        assert "Board Engineer" in partial.text
        assert "<!DOCTYPE html>" not in partial.text
    finally:
        close_pool()
        with psycopg.connect(database_url) as conn:
            conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
            conn.execute("DELETE FROM companies WHERE id = %s", (company_id,))
            conn.commit()

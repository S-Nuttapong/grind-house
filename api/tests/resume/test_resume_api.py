"""Resume and admin usage routes. The agent is the fake one, so nothing leaves the machine."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from jobhunt import composition
from jobhunt.app import create_app
from jobhunt.brag import repo as brag_repo
from jobhunt.core.db import close_pool
from jobhunt.fit import repo as fit_repo
from jobhunt.fit.base import BragDoc
from jobhunt.fit.fake import FakeFitScorer
from jobhunt.resume.fake import FakeResumeWriter
from jobhunt.resume.worker import execute_run
from jobhunt.scrape import repo as scrape_repo

_TEXT = "Built React services for payment teams."


@pytest.fixture
def client(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(
        composition,
        "COMPOSITION",
        replace(
            composition.COMPOSITION,
            scorer=FakeFitScorer(),
            writer=FakeResumeWriter(),
        ),
    )
    close_pool()
    with TestClient(create_app()) as test_client:
        yield test_client
    close_pool()
    with psycopg.connect(database_url) as conn:
        for table in (
            "agent_usage",
            "resume_artifacts",
            "resume_run_events",
            "resume_runs",
            "job_fit_matches",
            "job_fits",
            "fit_sources",
            "postings",
            "jobs",
            "brag_docs",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()


def _seed(conn: psycopg.Connection) -> int:
    slug = uuid4().hex[:8]
    company_id = scrape_repo.insert_company(
        conn, name=f"Api Resume {slug}", name_norm=f"api resume {slug}"
    )
    job_id = scrape_repo.insert_job(
        conn,
        company_id=company_id,
        title="Payments",
        title_norm=f"payments {slug}",
        apply_url=f"https://example.com/resume-api-{slug}",
        dedupe_key=f"{company_id}|payments|SG",
        description_md=_TEXT,
    )
    brag_repo.save_brag_doc(
        conn,
        {
            "id": f"BB-{slug}",
            "title": "React payments",
            "date": date(2026, 10, 8),
            "company": "Acme",
            "role": "Engineer",
            "description_md": _TEXT,
            "origin": "ui",
            "impact": 3,
            "tag_ids": [],
            "metrics": [],
            "attachments": [],
        },
    )
    source = f"api-{slug}"
    baseline = FakeFitScorer().fit([BragDoc(id=f"BB-{slug}", text=_TEXT)], _TEXT)
    fit_repo.upsert_fit_source(conn, source_hash=source, kind="bank", resume_id=None)
    fit_repo.mark_source_scored(conn, source)
    fit_repo.upsert_job_fit(
        conn,
        {
            "job_id": job_id,
            "model_id": "fake/v1",
            "source_hash": source,
            "job_hash": "hash",
            "score": baseline.score,
            "raw": baseline.raw,
            "coverage": baseline.coverage,
            "gaps": [],
            "matched_terms": [],
            "missing_terms": [],
        },
    )
    fit_repo.replace_matches(
        conn,
        job_id=job_id,
        model_id="fake/v1",
        source_hash=source,
        matches=[{"doc_ref": f"BB-{slug}", "aspect": _TEXT, "similarity": 0.9}],
    )
    return job_id


def test_enqueue_requires_a_scored_job_then_serves_the_pdf(
    client: TestClient, database_url: str
) -> None:
    missing = client.post("/api/jobs/999999/resume")
    assert missing.status_code == 404

    with psycopg.connect(database_url) as conn:
        company_id = scrape_repo.insert_company(conn, name="Bare", name_norm="bare resume api")
        bare = scrape_repo.insert_job(
            conn,
            company_id=company_id,
            title="Bare",
            title_norm="bare",
            apply_url="https://example.com/bare-resume",
            dedupe_key=f"{company_id}|bare|SG",
            description_md="Nothing scored.",
        )
        job_id = _seed(conn)
        conn.commit()

    blocked = client.post(f"/api/jobs/{bare}/resume")
    assert blocked.status_code == 409

    queued = client.post(f"/api/jobs/{job_id}/resume")
    assert queued.status_code == 202
    run_id = queued.json()["run_id"]
    again = client.post(f"/api/jobs/{job_id}/resume")
    assert again.status_code == 202 and again.json()["run_id"] == run_id

    execute_run(FakeResumeWriter(), FakeFitScorer(), run_id)

    listed = client.get(f"/api/jobs/{job_id}/resume-runs")
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "ok"

    pdf = client.get(f"/api/resume-runs/{run_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "attachment" in pdf.headers["content-disposition"]
    assert pdf.content.startswith(b"%PDF")

    usage = client.get("/api/admin/usage?days=30")
    assert usage.status_code == 200
    body = usage.json()
    assert body["runs"] >= 1
    assert body["recent"][0]["run_id"] == run_id


def test_brag_impact_round_trip(client: TestClient) -> None:
    created = client.post(
        "/api/brag-docs",
        json={"title": "Rated", "date": "2026-10-08", "description_md": "Shipped.", "impact": 4},
    )
    assert created.status_code == 201
    assert created.json()["impact"] == 4
    doc_id = created.json()["id"]
    cleared = client.put(
        f"/api/brag-docs/{doc_id}",
        json={"title": "Rated", "date": "2026-10-08", "description_md": "Shipped.", "impact": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["impact"] is None

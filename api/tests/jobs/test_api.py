"""The JSON API lists, filters, details, and records events for the Next.js board."""

from collections.abc import Iterator
from datetime import date, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from jobhunt.app import create_app
from jobhunt.composition import COMPOSITION
from jobhunt.core.db import close_pool
from jobhunt.fit import repo as fit_repo
from jobhunt.scrape import repo


@pytest.fixture
def seeded(database_url: str) -> Iterator[dict[str, int]]:
    close_pool()
    today = date.today()
    with psycopg.connect(database_url) as conn:
        company_id = repo.insert_company(conn, name="Api Co", name_norm="api co zz", tier="B")
        new_id = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzApi Board Engineer",
            title_norm="zzapi board engineer",
            apply_url="https://example.com/api-board",
            dedupe_key=f"{company_id}|zzapi board engineer|SG",
            country="SG",
            city="ZzApiville",
            role="frontend",
            industry="fintech",
            salary_min=120000,
            salary_currency="USD",
            posted_at=today,
            description_md="Ships the board.\n\n<script>alert(1)</script>",
        )
        old_id = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzApi Old Role",
            title_norm="zzapi old role",
            apply_url="https://example.com/api-old",
            dedupe_key=f"{company_id}|zzapi old role|US",
            country="US",
            city="Otherplace",
            posted_at=today - timedelta(days=40),
            description_md="An older role.",
        )
        conn.commit()
    try:
        yield {"new": new_id, "old": old_id}
    finally:
        close_pool()
        with psycopg.connect(database_url) as conn:
            conn.execute("DELETE FROM jobs WHERE id = ANY(%s)", ([new_id, old_id],))
            conn.execute("DELETE FROM companies WHERE id = %s", (company_id,))
            conn.commit()


def _titles(client: TestClient, **params: str) -> list[str]:
    response = client.get("/api/jobs", params={"q": "ZzApi", **params})
    assert response.status_code == 200
    return [job["title"] for job in response.json()["jobs"]]


def test_list_filters_and_shape(seeded: dict[str, int]) -> None:
    client = TestClient(create_app())
    body = client.get("/api/jobs", params={"q": "ZzApi"}).json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["pages"] == 1
    newest = body["jobs"][0]
    assert newest["title"] == "ZzApi Board Engineer"
    assert newest["salary_min"] == "120000"
    assert newest["is_new"] is True
    assert newest["age"] == "0d"
    assert _titles(client, posted_within="30") == ["ZzApi Board Engineer"]
    assert newest["score"] is None
    assert newest["stage"] == "not scored"

    assert _titles(client, where="ZzApiville") == ["ZzApi Board Engineer"]
    assert _titles(client, posted_within="1") == ["ZzApi Board Engineer"]
    assert _titles(client, has_salary="1") == ["ZzApi Board Engineer"]
    assert _titles(client, country="SG,US") == ["ZzApi Board Engineer", "ZzApi Old Role"]
    assert _titles(client, country="SG") == ["ZzApi Board Engineer"]
    assert _titles(client, country="ZZ") == ["ZzApi Board Engineer", "ZzApi Old Role"]
    assert _titles(client, region="apac") == ["ZzApi Board Engineer"]
    assert _titles(client, region="north_america") == ["ZzApi Old Role"]
    assert _titles(client, region="mars") == ["ZzApi Board Engineer", "ZzApi Old Role"]
    assert _titles(client, role="frontend") == ["ZzApi Board Engineer"]
    assert _titles(client, role="backend,frontend") == ["ZzApi Board Engineer"]
    assert _titles(client, role="not-a-role") == ["ZzApi Board Engineer", "ZzApi Old Role"]
    assert _titles(client, industry="fintech") == ["ZzApi Board Engineer"]


def test_query_filters_before_every_sort(database_url: str) -> None:
    """A newer unrelated job stays out. Sort only reorders the matches."""
    close_pool()
    today = date.today()
    source = "sort-relevance-test"
    with psycopg.connect(database_url) as conn:
        company_id = repo.insert_company(conn, name="Sort Co", name_norm="sort co zz")
        high = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzSortRel Senior",
            title_norm="zzsortrel senior",
            apply_url="https://example.com/sort-high",
            dedupe_key=f"{company_id}|zzsortrel senior|SG",
            posted_at=today - timedelta(days=2),
            description_md="ZzSortRel payments.",
        )
        low = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzSortRel Junior",
            title_norm="zzsortrel junior",
            apply_url="https://example.com/sort-low",
            dedupe_key=f"{company_id}|zzsortrel junior|SG",
            posted_at=today - timedelta(days=10),
            description_md="ZzSortRel support.",
        )
        unscored = repo.insert_job(
            conn,
            company_id=company_id,
            title="ZzSortRel Intern",
            title_norm="zzsortrel intern",
            apply_url="https://example.com/sort-open",
            dedupe_key=f"{company_id}|zzsortrel intern|SG",
            posted_at=today - timedelta(days=5),
            description_md="ZzSortRel internship.",
        )
        noise = repo.insert_job(
            conn,
            company_id=company_id,
            title="Night Cashier",
            title_norm="night cashier",
            apply_url="https://example.com/sort-noise",
            dedupe_key=f"{company_id}|night cashier|SG",
            posted_at=today,
            description_md="Register and floor.",
        )
        fit_repo.upsert_fit_source(conn, source_hash=source, kind="bank", resume_id=None)
        fit_repo.mark_source_scored(conn, source)
        for job_id, score in ((high, 90.0), (low, 20.0), (noise, 99.0)):
            fit_repo.upsert_job_fit(
                conn,
                {
                    "job_id": job_id,
                    "model_id": COMPOSITION.scorer.model_id,
                    "source_hash": source,
                    "job_hash": f"job-{job_id}",
                    "score": score,
                    "raw": score / 100,
                    "matched_terms": [],
                    "missing_terms": [],
                },
            )
        conn.commit()
    client = TestClient(create_app())
    try:
        assert _titles(client, q="ZzSortRel") == [
            "ZzSortRel Senior",
            "ZzSortRel Intern",
            "ZzSortRel Junior",
        ]
        assert _titles(client, q="ZzSortRel", sort="oldest") == [
            "ZzSortRel Junior",
            "ZzSortRel Intern",
            "ZzSortRel Senior",
        ]
        assert _titles(client, q="ZzSortRel", sort="fit_desc") == [
            "ZzSortRel Senior",
            "ZzSortRel Junior",
            "ZzSortRel Intern",
        ]
        assert _titles(client, q="ZzSortRel", sort="match") == [
            "ZzSortRel Senior",
            "ZzSortRel Junior",
            "ZzSortRel Intern",
        ]
        assert _titles(client, q="ZzSortRel", sort="fit_asc") == [
            "ZzSortRel Junior",
            "ZzSortRel Senior",
            "ZzSortRel Intern",
        ]
    finally:
        close_pool()
        with psycopg.connect(database_url) as conn:
            conn.execute(
                "DELETE FROM jobs WHERE id = ANY(%s)",
                ([high, low, unscored, noise],),
            )
            conn.execute("DELETE FROM companies WHERE id = %s", (company_id,))
            conn.execute("DELETE FROM fit_sources WHERE hash = %s", (source,))
            conn.commit()


def test_detail_returns_markdown_as_data(seeded: dict[str, int]) -> None:
    client = TestClient(create_app())
    detail = client.get(f"/api/jobs/{seeded['new']}")
    assert detail.status_code == 200
    body = detail.json()
    assert "<script>alert(1)</script>" in body["description_md"]
    assert body["tailor_prompt"].startswith(f"Tailor my resume for jobhunt job #{seeded['new']}")
    assert client.get("/api/jobs/999999999").status_code == 404


def test_events_update_status_and_pipeline(seeded: dict[str, int]) -> None:
    client = TestClient(create_app())
    saved = client.post(f"/api/jobs/{seeded['new']}/events", json={"status": "saved"})
    assert saved.status_code == 200
    assert saved.json()["status"] == "saved"
    assert saved.json()["events"][0]["status"] == "saved"

    skipped = client.post(
        f"/api/jobs/{seeded['old']}/events", json={"status": "skipped", "reason": " too old "}
    )
    assert skipped.json()["events"][0]["reason"] == "too old"

    bogus = client.post(f"/api/jobs/{seeded['new']}/events", json={"status": "bogus"})
    assert bogus.status_code == 422

    pipeline = client.get("/api/pipeline").json()
    assert seeded["new"] in [job["id"] for job in pipeline["saved"]]
    assert seeded["old"] in [job["id"] for job in pipeline["skipped"]]


def test_facets_and_runs(seeded: dict[str, int]) -> None:
    client = TestClient(create_app())
    facets = client.get("/api/facets").json()
    assert "remote" in facets["remote"]
    assert isinstance(facets["sources"], list)
    assert "SG" in facets["countries"]
    assert "apac" in facets["regions"]
    assert "frontend" in facets["roles"]
    assert "fintech" in facets["industries"]
    assert "senior" in facets["levels"]
    assert client.get("/api/runs").status_code == 200

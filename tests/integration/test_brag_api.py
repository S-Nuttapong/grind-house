from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from jobhunt.db import close_pool
from jobhunt.web.app import create_app


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    close_pool()
    with TestClient(create_app()) as test_client:
        yield test_client
    close_pool()
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM brag_docs")
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM metric_keys")
        conn.commit()


def test_create_lists_and_filters_unknown_ids(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "Backend"})
    assert tag.status_code == 200
    assert tag.json()["created"] is True
    key = client.post("/api/metric-keys", json={"name": "Latency Reduction"})
    assert key.json()["created"] is True

    missing = client.post(
        "/api/brag-docs",
        json={"title": "Nope", "date": "2026-10-08", "tag_ids": [99999]},
    )
    assert missing.status_code == 422

    created = client.post(
        "/api/brag-docs",
        json={
            "title": "Migrated legacy auth",
            "date": "2026-10-08",
            "company": "Acme Corp",
            "role": "Engineer",
            "tag_ids": [tag.json()["id"]],
            "metrics": [{"metric_key_id": key.json()["id"], "value": "200ms"}],
            "attachments": [{"type": "url", "link": "https://example.com/pr"}],
            "description_md": "Zero downtime.",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["id"] == "BB-001"
    assert body["quarter"] == "Q4 2026"
    assert body["origin"] == "ui"
    assert body["metrics"][0]["name"] == "Latency Reduction"

    blank = client.post("/api/brag-docs", json={"title": " ", "date": "2026-10-08"})
    assert blank.status_code == 422
    bad_link = client.post(
        "/api/brag-docs",
        json={
            "title": "Link",
            "date": "2026-10-08",
            "attachments": [{"type": "url", "link": "ftp://files"}],
        },
    )
    assert bad_link.status_code == 422

    listed = client.get("/api/brag-docs").json()
    assert [doc["id"] for doc in listed] == ["BB-001"]
    assert client.get("/api/brag-docs/companies").json() == ["Acme Corp"]

    updated = client.put(
        "/api/brag-docs/BB-001",
        json={"title": "Migrated auth", "date": "2026-10-08", "description_md": "Still zero."},
    )
    assert updated.json()["title"] == "Migrated auth"
    assert updated.json()["origin"] == "ui"
    assert updated.json()["tags"] == []

    assert client.delete("/api/brag-docs/BB-001").status_code == 204
    assert client.get("/api/brag-docs/BB-001").status_code == 404
    assert client.delete("/api/brag-docs/BB-001").status_code == 404


def test_tag_and_metric_key_post_is_idempotent(client: TestClient) -> None:
    first = client.post("/api/tags", json={"name": "React"}).json()
    second = client.post("/api/tags", json={"name": "react"}).json()
    assert second["id"] == first["id"]
    assert second["created"] is False
    assert second["name"] == "React"

    key = client.post("/api/metric-keys", json={"name": "Engineering Hours Saved"}).json()
    again = client.post("/api/metric-keys", json={"name": "engineering hours saved"}).json()
    assert again["id"] == key["id"]
    assert again["created"] is False

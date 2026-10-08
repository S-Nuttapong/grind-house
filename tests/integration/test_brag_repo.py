from datetime import date

import psycopg
import pytest
from jobhunt.db import brag_repo


def _doc(doc_id: str, **overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "id": doc_id,
        "title": "Migrated legacy auth",
        "date": date(2026, 10, 8),
        "company": "Acme Corp",
        "role": "Engineer",
        "description_md": "Zero downtime.",
        "origin": "ui",
        "tag_ids": [],
        "metrics": [],
        "attachments": [],
    }
    doc.update(overrides)
    return doc


def test_quarter_is_derived_and_children_are_replaced(conn) -> None:
    backend, _ = brag_repo.get_or_create_tag(conn, "Backend")
    latency, _ = brag_repo.get_or_create_metric_key(conn, "Latency Reduction")
    saved = brag_repo.save_brag_doc(
        conn,
        _doc(
            "BB-010",
            tag_ids=[backend["id"]],
            metrics=[{"metric_key_id": latency["id"], "value": "200ms"}],
            attachments=[{"type": "url", "link": "https://example.com/pr"}],
        ),
    )
    assert saved["quarter"] == "Q4 2026"
    assert saved["date"] == date(2026, 10, 8)
    assert saved["metrics"][0]["name"] == "Latency Reduction"
    assert saved["metrics"][0]["value"] == "200ms"

    hours, _ = brag_repo.get_or_create_metric_key(conn, "Engineering Hours Saved")
    replaced = brag_repo.save_brag_doc(
        conn,
        _doc(
            "BB-010",
            tag_ids=[],
            metrics=[{"metric_key_id": hours["id"], "value": "15 hours/week"}],
            attachments=[],
        ),
    )
    assert replaced["tags"] == []
    assert [metric["name"] for metric in replaced["metrics"]] == ["Engineering Hours Saved"]
    assert replaced["attachments"] == []
    assert brag_repo.list_companies(conn) == ["Acme Corp"]


def test_get_or_create_is_case_insensitive(conn) -> None:
    first, created = brag_repo.get_or_create_tag(conn, "React")
    again, created_again = brag_repo.get_or_create_tag(conn, " react ")
    assert created is True
    assert created_again is False
    assert again["id"] == first["id"]
    assert again["name"] == "React"

    key, _ = brag_repo.get_or_create_metric_key(conn, "Latency Reduction")
    same, created_key = brag_repo.get_or_create_metric_key(conn, "latency reduction")
    assert created_key is False
    assert same["id"] == key["id"]


def test_delete_cascades_children_but_not_the_metric_key(conn) -> None:
    tag, _ = brag_repo.get_or_create_tag(conn, "Backend")
    key, _ = brag_repo.get_or_create_metric_key(conn, "Latency Reduction")
    brag_repo.save_brag_doc(
        conn,
        _doc(
            "BB-011",
            tag_ids=[tag["id"]],
            metrics=[{"metric_key_id": key["id"], "value": "200ms"}],
        ),
    )
    assert brag_repo.delete_brag_doc(conn, "BB-011") is True
    assert brag_repo.get_brag_doc(conn, "BB-011") is None
    assert brag_repo.list_metric_keys(conn)[0]["name"] == "Latency Reduction"
    assert brag_repo.list_tags(conn)[0]["name"] == "Backend"

    brag_repo.save_brag_doc(
        conn,
        _doc("BB-012", metrics=[{"metric_key_id": key["id"], "value": "1ms"}]),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            conn.execute("DELETE FROM metric_keys WHERE id = %s", (key["id"],))


def test_next_id_skips_the_highest_number(conn) -> None:
    assert brag_repo.next_brag_doc_id(conn) == "BB-001"
    brag_repo.save_brag_doc(conn, _doc("BB-007"))
    assert brag_repo.next_brag_doc_id(conn) == "BB-008"

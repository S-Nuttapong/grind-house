from pathlib import Path

from jobhunt.db import fit_repo, repo
from jobhunt.fit.fake import FakeFitModel
from jobhunt.fit.import_bank import import_bank
from jobhunt.fit.runner import run_fit

_BANK = Path(__file__).resolve().parents[1] / "fixtures" / "bank"


def test_import_stores_entries_without_contact_details(conn) -> None:
    counts = import_bank(conn, _BANK)
    assert counts == {"entries": 2, "resumes": 1}

    entries = {entry["id"]: entry for entry in fit_repo.list_bank_entries(conn)}
    assert entries["BB-001"]["tags"] == ["skill/go", "skill/kafka"]
    assert entries["BB-001"]["metrics"][0]["text"] == "retries -38%"
    assert "payments retry scheduler" in entries["BB-001"]["body_md"]
    assert entries["BB-002"]["confidential"] is True

    profile = fit_repo.get_bank_profile(conn)
    assert "Timeline" in profile
    assert "test@example.com" not in profile
    assert "555-0100" not in profile

    resumes = fit_repo.list_resumes(conn)
    assert resumes[0]["origin"] == "vault"
    full = fit_repo.get_resume(conn, resumes[0]["id"])
    assert full is not None
    assert "payment systems" in full["text"]
    assert "555-0100" not in full["text"]


def test_run_fit_is_incremental_and_rescored_after_an_edit(conn) -> None:
    import_bank(conn, _BANK)
    company_id = repo.insert_company(conn, name="Import Co", name_norm="import co")
    first = repo.insert_job(
        conn,
        company_id=company_id,
        title="Go and Kafka engineer",
        title_norm="go and kafka engineer",
        apply_url="https://example.com/a",
        dedupe_key=f"{company_id}|go|SG",
        description_md="We use Go and Kafka for fintech payments.",
    )
    second = repo.insert_job(
        conn,
        company_id=company_id,
        title="Designer",
        title_norm="designer",
        apply_url="https://example.com/b",
        dedupe_key=f"{company_id}|designer|SG",
        description_md="Brand design, no overlap with the bank.",
    )

    model = FakeFitModel()
    first_run = run_fit(conn, model, "bank")
    assert first_run == {"scored": 2, "skipped": 0}

    scores = dict(conn.execute("SELECT job_id, score FROM job_fits ORDER BY job_id").fetchall())
    assert scores[first] > scores[second]

    assert run_fit(conn, model, "bank") == {"scored": 0, "skipped": 2}

    fit_repo.upsert_bank_entry(
        conn,
        {
            "id": "BB-003",
            "title": "Design system",
            "company": "Example Co",
            "role": "Engineer",
            "period": "2025",
            "my_role": "built",
            "scope": None,
            "metrics": [],
            "strength": 3,
            "confidential": False,
            "status": "verified",
            "tags": ["skill/figma"],
            "body_md": "Built the design system.",
            "origin": "ui",
        },
    )
    rescored = run_fit(conn, model, "bank")
    assert rescored["scored"] == 2
    assert rescored["skipped"] == 0

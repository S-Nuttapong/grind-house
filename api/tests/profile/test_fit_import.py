from datetime import date
from pathlib import Path

from jobhunt.brag import repo as brag_repo
from jobhunt.fit.fake import FakeFitScorer
from jobhunt.fit.runner import run_fit
from jobhunt.profile import repo as profile_repo
from jobhunt.profile.import_bank import import_bank
from jobhunt.scrape import repo


def test_import_stores_entries_without_contact_details(conn, bank_dir: Path) -> None:
    counts = import_bank(conn, bank_dir)
    assert counts == {"entries": 2, "resumes": 1}

    entries = {entry["id"]: entry for entry in brag_repo.list_brag_docs(conn)}
    assert [tag["name"] for tag in entries["BB-001"]["tags"]] == ["skill/go", "skill/kafka"]
    assert entries["BB-001"]["metrics"][0]["name"] == "General"
    assert entries["BB-001"]["metrics"][0]["value"] == "retries -38%"
    assert entries["BB-001"]["date"] == date(2023, 6, 30)
    assert entries["BB-001"]["quarter"] == "Q2 2023"
    assert entries["BB-001"]["attachments"][0]["link"] == "https://example.com/payments"
    assert "payments retry scheduler" in entries["BB-001"]["description_md"]
    assert entries["BB-002"]["date"] == date(2024, 2, 29)

    profile = profile_repo.get_bank_profile(conn)
    assert "Timeline" in profile
    assert "test@example.com" not in profile
    assert "555-0100" not in profile

    resumes = profile_repo.list_resumes(conn)
    assert resumes[0]["origin"] == "vault"
    full = profile_repo.get_resume(conn, resumes[0]["id"])
    assert full is not None
    assert "payment systems" in full["text"]
    assert "555-0100" not in full["text"]


def test_run_fit_is_incremental_and_rescored_after_an_edit(conn, bank_dir: Path) -> None:
    import_bank(conn, bank_dir)
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

    model = FakeFitScorer()
    first_run = run_fit(conn, model, "bank")
    assert first_run == {"scored": 2, "skipped": 0}

    scores = dict(conn.execute("SELECT job_id, score FROM job_fits ORDER BY job_id").fetchall())
    assert scores[first] > scores[second]

    assert run_fit(conn, model, "bank") == {"scored": 0, "skipped": 2}

    tag, _created = brag_repo.get_or_create_tag(conn, "skill/figma")
    brag_repo.save_brag_doc(
        conn,
        {
            "id": "BB-003",
            "title": "Design system",
            "date": date(2025, 6, 30),
            "company": "Example Co",
            "role": "Engineer",
            "description_md": "Built the design system.",
            "origin": "ui",
            "tag_ids": [tag["id"]],
            "metrics": [],
            "attachments": [],
        },
    )
    rescored = run_fit(conn, model, "bank")
    assert rescored["scored"] == 2
    assert rescored["skipped"] == 0

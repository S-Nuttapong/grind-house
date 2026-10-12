"""Queue, lease, cost log, impact, and the resume migration."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
from jobhunt.brag import repo as brag_repo
from jobhunt.profile.import_bank import import_bank
from jobhunt.resume import repo
from jobhunt.scrape import repo as scrape_repo


def _job(conn) -> int:
    company_id = scrape_repo.insert_company(conn, name="Resume Co", name_norm="resume co repo")
    return scrape_repo.insert_job(
        conn,
        company_id=company_id,
        title="Backend",
        title_norm="backend",
        apply_url="https://example.com/resume-repo",
        dedupe_key=f"{company_id}|backend|SG",
        description_md="Go services.",
    )


def _doc(doc_id: str, **overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "id": doc_id,
        "title": "Shipped the ledger",
        "date": date(2026, 10, 8),
        "company": "Acme",
        "role": "Engineer",
        "description_md": "Cut retries.",
        "origin": "ui",
        "tag_ids": [],
        "metrics": [],
        "attachments": [],
    }
    doc.update(overrides)
    return doc


def test_enqueue_is_idempotent_and_a_dead_lease_can_be_claimed(conn) -> None:
    job_id = _job(conn)
    first, created = repo.enqueue(
        conn,
        job_id=job_id,
        agent_id="fake/v1",
        model="fake",
        fit_model_id="fake/v1",
        fit_source_hash="src",
    )
    again, created_again = repo.enqueue(
        conn,
        job_id=job_id,
        agent_id="fake/v1",
        model="fake",
        fit_model_id="fake/v1",
        fit_source_hash="src",
    )
    assert created is True
    assert created_again is False
    assert again == first

    claimed = repo.claim(conn)
    assert claimed is not None and claimed["id"] == first
    assert claimed["status"] == "running"
    assert repo.claim(conn) is None

    conn.execute(
        "UPDATE resume_runs SET locked_until = now() - interval '1 minute' WHERE id = %s",
        (first,),
    )
    reclaimed = repo.claim(conn)
    assert reclaimed is not None and reclaimed["id"] == first


def test_usage_summary_groups_by_day_and_model(conn) -> None:
    job_id = _job(conn)
    run_id, _created = repo.enqueue(
        conn,
        job_id=job_id,
        agent_id="fake/v1",
        model="fake",
        fit_model_id="fake/v1",
        fit_source_hash="src",
    )
    for attempt, model, cost in ((1, "claude-haiku-5-5", "0.010000"), (2, "fake", "0.020000")):
        repo.record_usage(
            conn,
            run_id,
            attempt,
            {
                "agent_id": "fake/v1",
                "model": model,
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "num_turns": 1,
                "duration_ms": 5,
                "cost_usd": Decimal(cost),
                "cost_source": "computed",
            },
        )
    summary = repo.usage_summary(conn, days=30)
    assert summary["runs"] == 2
    assert summary["cost_usd"] == Decimal("0.030000")
    assert {row["model"] for row in summary["by_day"]} == {"claude-haiku-5-5", "fake"}
    assert summary["recent"][0]["job_id"] == job_id


def test_impact_round_trips_and_import_keeps_a_rating_the_vault_omits(conn, tmp_path: Path) -> None:
    saved = brag_repo.save_brag_doc(conn, _doc("BB-900", impact=4))
    assert saved["impact"] == 4
    kept = brag_repo.save_brag_doc(conn, _doc("BB-900"))
    assert kept["impact"] == 4

    bank = tmp_path / "bank"
    entries = bank / "Entries"
    entries.mkdir(parents=True)
    (entries / "BB-900.md").write_text(
        "---\nid: BB-900\ntitle: Shipped the ledger\ndate: 2026-10-08\n---\nCut retries.\n"
    )
    (entries / "BB-901.md").write_text(
        "---\nid: BB-901\ntitle: Other\ndate: 2026-10-08\nimpact: 5\n---\nLed the migration.\n"
    )
    import_bank(conn, bank)
    docs = {doc["id"]: doc for doc in brag_repo.list_brag_docs(conn)}
    assert docs["BB-900"]["impact"] == 4
    assert docs["BB-901"]["impact"] == 5


def test_resume_migration_round_trip(conn: psycopg.Connection) -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "db"
        / "migrations"
        / "20261011000006_resume_agent.sql"
    )
    text = migration.read_text()
    up, down = text.split("-- migrate:down", 1)
    up = up.split("-- migrate:up", 1)[1]
    with psycopg.ClientCursor(conn) as cursor:
        cursor.execute(down)
        cursor.execute(up)
    impact = conn.execute(
        """
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'brag_docs' AND column_name = 'impact'
        """
    ).fetchone()
    assert impact is not None and impact[0] == "smallint"
    for table in ("resume_runs", "resume_run_events", "resume_artifacts", "agent_usage"):
        found = conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()
        assert found is not None and found[0] == table

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from jobhunt.db import fit_repo, repo


def _job(conn, company_id: int, title: str) -> int:
    return repo.insert_job(
        conn,
        company_id=company_id,
        title=title,
        title_norm=title.lower(),
        apply_url=f"https://example.com/{title}",
        dedupe_key=f"{company_id}|{title.lower()}|SG",
    )


def test_profile_and_resume_selection(conn) -> None:
    assert fit_repo.get_bank_profile(conn) == ""
    fit_repo.set_bank_profile(conn, "Timeline goes here.")
    assert fit_repo.get_bank_profile(conn) == "Timeline goes here."

    first = fit_repo.insert_resume(
        conn, name="One", text="resume one", filename=None, origin="upload"
    )
    second = fit_repo.insert_resume(
        conn, name="Two", text="resume two", filename="two.pdf", origin="vault"
    )
    assert fit_repo.select_resume(conn, first) is True
    assert fit_repo.select_resume(conn, second) is True
    selected = fit_repo.selected_resume(conn)
    assert selected is not None and selected["id"] == second
    assert len(fit_repo.list_resumes(conn)) == 2
    assert fit_repo.delete_resume(conn, first) is True


def test_one_selected_resume_is_enforced(conn) -> None:
    fit_repo.insert_resume(conn, name="A", text="a", filename=None, origin="upload")
    fit_repo.insert_resume(conn, name="B", text="b", filename=None, origin="upload")
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("UPDATE resumes SET is_selected = true")


def test_enqueue_is_idempotent_and_claim_skips_locked(conn, database_url: str) -> None:
    run = {
        "schedule_id": None,
        "mode": "bank",
        "trigger": "manual",
        "model_id": "fake/v1",
        "idempotency_key": "same-key",
    }
    first_id, created = fit_repo.enqueue_run(conn, run)
    assert created is True
    again_id, created_again = fit_repo.enqueue_run(conn, run)
    assert created_again is False
    assert again_id == first_id

    fit_repo.enqueue_run(conn, {**run, "idempotency_key": "other-key"})
    conn.commit()

    other = psycopg.connect(database_url)
    try:
        claimed = fit_repo.claim_run(other)
        assert claimed is not None and claimed["id"] == first_id
        blocked = fit_repo.claim_run(conn)
        assert blocked is not None and blocked["id"] != first_id
    finally:
        other.rollback()
        other.close()


def test_run_events_progress_and_worker(conn) -> None:
    run_id, _ = fit_repo.enqueue_run(
        conn,
        {
            "schedule_id": None,
            "mode": "bank",
            "trigger": "manual",
            "model_id": "fake/v1",
            "idempotency_key": "events",
        },
    )
    event_id = fit_repo.add_run_event(
        conn, run_id, "progress", {"done": 10, "total": 40, "pct": 25}
    )
    fit_repo.notify_run(conn, run_id, event_id)
    fit_repo.add_run_event(conn, run_id, "status", {"status": "ok"})

    assert [event["id"] for event in fit_repo.run_events_after(conn, run_id, 0)] == [
        event_id,
        event_id + 1,
    ]
    assert fit_repo.run_events_after(conn, run_id, event_id)[0]["kind"] == "status"
    progress = fit_repo.latest_progress(conn, run_id)
    assert progress is not None and progress["payload"]["pct"] == 25

    fit_repo.finish_fit_run(conn, run_id, status="ok", scored=40, skipped=3, error=None)
    finished = fit_repo.get_run(conn, run_id)
    assert finished is not None and finished["status"] == "ok" and finished["scored"] == 40

    fit_repo.requeue_run(conn, run_id)
    requeued = fit_repo.get_run(conn, run_id)
    assert requeued is not None and requeued["status"] == "queued"

    fit_repo.heartbeat(conn, "fake/v1")
    assert fit_repo.worker_status(conn)["model_id"] == "fake/v1"


def test_schedules_and_job_fits(conn) -> None:
    seeded = fit_repo.list_schedules(conn)
    assert {row["name"] for row in seeded} == {
        "Brag bank daily 06:00",
        "Selected resume daily 06:30",
    }

    schedule_id = fit_repo.insert_schedule(
        conn,
        {
            "name": "Hourly",
            "mode": "bank",
            "cron": "0 * * * *",
            "timezone": "Asia/Bangkok",
            "enabled": True,
            "next_run_at": datetime.now(UTC) - timedelta(minutes=5),
        },
    )
    due = fit_repo.due_schedules(conn, datetime.now(UTC))
    assert schedule_id in {row["id"] for row in due}
    assert fit_repo.update_schedule(conn, schedule_id, {"enabled": False}) is True
    assert schedule_id not in {row["id"] for row in fit_repo.due_schedules(conn, datetime.now(UTC))}
    assert fit_repo.delete_schedule(conn, schedule_id) is True

    company_id = repo.insert_company(conn, name="Fit Co", name_norm="fit co")
    job_id = _job(conn, company_id, "Backend Engineer")
    fit_repo.upsert_fit_source(conn, source_hash="abc", kind="bank", resume_id=None)
    fit_repo.upsert_fit_source(conn, source_hash="abc", kind="bank", resume_id=None)
    fit = {
        "job_id": job_id,
        "model_id": "fake/v1",
        "source_hash": "abc",
        "job_hash": "j1",
        "score": 82.5,
        "raw": 0.77,
        "matched_terms": ["go"],
        "missing_terms": ["rust"],
    }
    fit_repo.upsert_job_fit(conn, fit)
    fit_repo.upsert_job_fit(conn, {**fit, "score": 90.0, "job_hash": "j2"})
    stored = conn.execute(
        "SELECT score, job_hash FROM job_fits WHERE job_id = %s", (job_id,)
    ).fetchone()
    assert stored == (90.0, "j2")

    assert fit_repo.latest_scored_source(conn, "bank") is None
    fit_repo.mark_source_scored(conn, "abc")
    assert fit_repo.latest_scored_source(conn, "bank") == "abc"

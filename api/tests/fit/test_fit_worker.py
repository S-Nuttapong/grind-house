from datetime import UTC, datetime
from pathlib import Path

import psycopg
from jobhunt.fit import repo as fit_repo
from jobhunt.fit.fake import FakeFitModel
from jobhunt.fit.sources import job_hash
from jobhunt.fit.worker import execute_run, idempotency_key, poll_once, queue_run
from jobhunt.profile.import_bank import import_bank
from jobhunt.scrape import repo


def _open_job(conn, company_id: int, number: int) -> int:
    title = f"Role {number}"
    return repo.insert_job(
        conn,
        company_id=company_id,
        title=title,
        title_norm=title.lower(),
        apply_url=f"https://example.com/{number}",
        dedupe_key=f"{company_id}|{title.lower()}|SG",
        description_md="Go and Kafka for payments.",
    )


def test_idempotency_key_depends_on_slot_and_schedule() -> None:
    manual = idempotency_key("bank", "abc", "2026-10-08T06:00", None)
    same = idempotency_key("bank", "abc", "2026-10-08T06:00", None)
    other_slot = idempotency_key("bank", "abc", "2026-10-08T07:00", None)
    scheduled = idempotency_key("bank", "abc", "2026-10-08T06:00", 5)
    assert manual == same
    assert len({manual, other_slot, scheduled}) == 3


def test_double_queue_returns_the_same_run(conn) -> None:
    args = {
        "mode": "bank",
        "trigger": "manual",
        "model_id": "fake/v1",
        "source_hash": "abc",
        "slot": "2026-10-08T06:00",
    }
    first, created = queue_run(conn, **args)
    second, created_again = queue_run(conn, **args)
    assert created is True
    assert created_again is False
    assert first == second


def test_two_workers_claim_different_runs(committed, database_url: str) -> None:
    conn = committed
    for slot in ("one", "two"):
        queue_run(
            conn,
            mode="bank",
            trigger="manual",
            model_id="fake/v1",
            source_hash="abc",
            slot=slot,
        )
    conn.commit()
    other = psycopg.connect(database_url)
    try:
        first = fit_repo.claim_run(conn)
        second = fit_repo.claim_run(other)
        assert first is not None and second is not None
        assert first["id"] != second["id"]
    finally:
        other.rollback()
        other.close()


def test_run_records_progress_and_a_restart_scores_only_the_rest(committed, bank_dir: Path) -> None:
    conn = committed
    # Commit the setup: the worker commits on its own connection, and an open
    # transaction here would hide those commits.
    import_bank(conn, bank_dir)
    company_id = repo.insert_company(conn, name="Worker Co", name_norm="worker co")
    for number in range(3):
        _open_job(conn, company_id, number)
    run_id, _created = queue_run(
        conn,
        mode="bank",
        trigger="manual",
        model_id="fake/v1",
        source_hash="pending",
        slot="restart",
    )
    claimed = fit_repo.claim_run(conn)
    assert claimed is not None
    conn.commit()

    # Checked before each batch, so the second check is the one that stops it,
    # after the first job has been scored and committed.
    seen = {"checks": 0}

    def stop_after_first_batch() -> bool:
        seen["checks"] += 1
        return seen["checks"] > 1

    execute_run(FakeFitModel(), run_id, batch_size=1, should_stop=stop_after_first_batch)

    conn.commit()  # end the snapshot so the worker's commits are visible
    stored = conn.execute("SELECT count(*) FROM job_fits").fetchone()
    assert stored is not None and stored[0] == 1
    assert fit_repo.get_run(conn, run_id)["status"] == "queued"

    claimed_again = fit_repo.claim_run(conn)
    assert claimed_again is not None and claimed_again["id"] == run_id
    conn.commit()
    execute_run(FakeFitModel(), run_id)

    conn.commit()
    finished = fit_repo.get_run(conn, run_id)
    assert finished["status"] == "ok"
    assert finished["scored"] == 3
    progress = fit_repo.latest_progress(conn, run_id)
    assert progress is not None and progress["payload"]["pct"] == 100
    events = fit_repo.run_events_after(conn, run_id, 0)
    assert events[-1]["kind"] == "status"


def test_poll_runs_a_due_schedule(committed, bank_dir: Path) -> None:
    conn = committed
    # Only the schedule this test creates should be due.
    conn.execute("UPDATE fit_schedules SET enabled = false")
    import_bank(conn, bank_dir)
    company_id = repo.insert_company(conn, name="Poll Co", name_norm="poll co")
    _open_job(conn, company_id, 7)
    schedule_id = fit_repo.insert_schedule(
        conn,
        {
            "name": "Every hour",
            "mode": "bank",
            "cron": "0 * * * *",
            "timezone": "UTC",
            "enabled": True,
            "next_run_at": datetime(2026, 10, 8, tzinfo=UTC),
        },
    )
    conn.commit()

    poll_once(FakeFitModel(), now=datetime(2026, 10, 8, 6, tzinfo=UTC))

    conn.commit()
    runs = [run for run in fit_repo.list_runs(conn) if run["trigger"] == "schedule"]
    assert runs and runs[0]["status"] == "ok"
    schedule = fit_repo.get_schedule(conn, schedule_id)
    assert schedule is not None and schedule["next_run_at"] > datetime(2026, 10, 8, 6, tzinfo=UTC)
    assert fit_repo.worker_status(conn)["model_id"] == "fake/v1"


def _prepare(conn, bank_dir: Path, company: str) -> int:
    conn.execute("UPDATE fit_schedules SET enabled = false")
    import_bank(conn, bank_dir)
    return repo.insert_company(conn, name=company, name_norm=company.lower())


def _scrape_runs(conn) -> list[dict]:
    return [run for run in fit_repo.list_runs(conn) if run["trigger"] == "scrape"]


def test_poll_scores_a_job_ingested_later_the_same_day(committed, bank_dir: Path) -> None:
    conn = committed
    company_id = _prepare(conn, bank_dir, "Ingest Co")
    _open_job(conn, company_id, 1)
    conn.commit()

    poll_once(FakeFitModel(), now=datetime(2026, 10, 8, 6, 0, tzinfo=UTC))
    conn.commit()
    assert len(_scrape_runs(conn)) == 1
    assert _scrape_runs(conn)[0]["status"] == "ok"

    _open_job(conn, company_id, 2)
    conn.commit()
    poll_once(FakeFitModel(), now=datetime(2026, 10, 8, 6, 1, tzinfo=UTC))

    conn.commit()
    runs = _scrape_runs(conn)
    assert len(runs) == 2
    assert all(run["status"] == "ok" for run in runs)
    stored = conn.execute("SELECT count(*) FROM job_fits").fetchone()
    assert stored is not None and stored[0] == 2


def test_poll_queues_no_scrape_run_when_nothing_is_unscored(committed, bank_dir: Path) -> None:
    conn = committed
    company_id = _prepare(conn, bank_dir, "Quiet Co")
    _open_job(conn, company_id, 3)
    conn.commit()

    poll_once(FakeFitModel(), now=datetime(2026, 10, 8, 7, 0, tzinfo=UTC))
    conn.commit()
    assert len(_scrape_runs(conn)) == 1

    poll_once(FakeFitModel(), now=datetime(2026, 10, 8, 7, 1, tzinfo=UTC))
    conn.commit()
    assert len(_scrape_runs(conn)) == 1


def test_poll_rescores_a_job_whose_description_changed(committed, bank_dir: Path) -> None:
    conn = committed
    company_id = _prepare(conn, bank_dir, "Edit Co")
    job_id = _open_job(conn, company_id, 4)
    conn.commit()

    poll_once(FakeFitModel(), now=datetime(2026, 10, 8, 8, 0, tzinfo=UTC))
    conn.commit()
    before = conn.execute("SELECT job_hash FROM job_fits WHERE job_id = %s", (job_id,)).fetchone()
    assert before is not None

    revised = "Payments in Rust and Kafka."
    conn.execute("UPDATE jobs SET description_md = %s WHERE id = %s", (revised, job_id))
    conn.commit()
    poll_once(FakeFitModel(), now=datetime(2026, 10, 8, 8, 1, tzinfo=UTC))

    conn.commit()
    after = conn.execute("SELECT job_hash FROM job_fits WHERE job_id = %s", (job_id,)).fetchone()
    assert after is not None
    assert after[0] == job_hash("Role 4", revised)
    assert after[0] != before[0]
    assert len(_scrape_runs(conn)) == 2


def test_poll_does_not_queue_a_second_scrape_run_while_one_is_queued(
    committed, bank_dir: Path
) -> None:
    conn = committed
    company_id = _prepare(conn, bank_dir, "Queued Co")
    _open_job(conn, company_id, 5)
    queue_run(
        conn,
        mode="bank",
        trigger="scrape",
        model_id="fake/v1",
        source_hash="already",
        slot="queued",
    )
    conn.commit()

    poll_once(FakeFitModel(), now=datetime(2026, 10, 8, 9, 0, tzinfo=UTC))

    conn.commit()
    runs = _scrape_runs(conn)
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"

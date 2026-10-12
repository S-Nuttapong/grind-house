"""A full resume run against the fake agent. The worker commits on its own connection."""

from datetime import date
from uuid import uuid4

from jobhunt.brag import repo as brag_repo
from jobhunt.fit import repo as fit_repo
from jobhunt.fit.base import BragDoc
from jobhunt.fit.fake import FakeFitScorer
from jobhunt.resume import repo
from jobhunt.resume.fake import FakeResumeWriter
from jobhunt.resume.worker import execute_run
from jobhunt.scrape import repo as scrape_repo

_TEXT = "Built React services for payment teams."
_FILLER = "Owned Kafka pipelines for ledger events."


def _seed(conn) -> int:
    slug = uuid4().hex[:8]
    company_id = scrape_repo.insert_company(
        conn, name=f"Worker Resume {slug}", name_norm=f"worker resume {slug}"
    )
    job_id = scrape_repo.insert_job(
        conn,
        company_id=company_id,
        title="Payments",
        title_norm="payments",
        apply_url="https://example.com/resume-worker",
        dedupe_key=f"{company_id}|payments|SG",
        description_md=_TEXT,
    )
    brag_repo.save_brag_doc(
        conn,
        {
            "id": "BB-910",
            "title": "React payments",
            "date": date(2026, 10, 8),
            "company": "Acme",
            "role": "Engineer",
            "description_md": _TEXT,
            "origin": "ui",
            "impact": 5,
            "tag_ids": [],
            "metrics": [],
            "attachments": [],
        },
    )
    brag_repo.save_brag_doc(
        conn,
        {
            "id": "BB-911",
            "title": "Kafka",
            "date": date(2026, 10, 8),
            "company": "Acme",
            "role": "Engineer",
            "description_md": _FILLER,
            "origin": "ui",
            "impact": 4,
            "tag_ids": [],
            "metrics": [],
            "attachments": [],
        },
    )
    model = FakeFitScorer()
    baseline = model.fit([BragDoc(id="BB-910", text=_TEXT)], _TEXT)
    fit_repo.upsert_fit_source(conn, source_hash="resume-src", kind="bank", resume_id=None)
    fit_repo.mark_source_scored(conn, "resume-src")
    fit_repo.upsert_job_fit(
        conn,
        {
            "job_id": job_id,
            "model_id": "fake/v1",
            "source_hash": "resume-src",
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
        source_hash="resume-src",
        matches=[{"doc_ref": "BB-910", "aspect": _TEXT, "similarity": 0.9}],
    )
    return job_id


def _enqueue(conn, job_id: int) -> int:
    run_id, created = repo.enqueue(
        conn,
        job_id=job_id,
        agent_id="fake/v1",
        model="fake",
        fit_model_id="fake/v1",
        fit_source_hash="resume-src",
    )
    assert created is True
    return run_id


def test_worker_scores_a_job_that_has_no_shortlist(committed) -> None:
    conn = committed
    job_id = _seed(conn)
    fit_repo.replace_matches(
        conn, job_id=job_id, model_id="fake/v1", source_hash="resume-src", matches=[]
    )
    run_id = _enqueue(conn, job_id)
    conn.commit()

    execute_run(FakeResumeWriter(), FakeFitScorer(), run_id)

    stored = repo.get_run(conn, run_id)
    assert stored is not None and stored["status"] == "ok"
    assert stored["fit_model_id"] == "fake/v1"


def test_worker_stores_the_pdf_the_events_and_one_usage_row(committed) -> None:
    conn = committed
    job_id = _seed(conn)
    run_id = _enqueue(conn, job_id)
    conn.commit()

    execute_run(FakeResumeWriter(), FakeFitScorer(), run_id)

    conn.commit()
    stored = repo.get_run(conn, run_id)
    assert stored is not None
    assert stored["status"] == "ok"
    assert stored["filler_ids"] == ["BB-911"]
    artifact = repo.artifact(conn, run_id)
    assert artifact is not None and artifact["pdf"]
    events = repo.events_after(conn, run_id, 0)
    assert events[-1]["kind"] == "status"
    assert len(repo.usage_for_run(conn, run_id)) == 1


def test_retries_end_below_baseline_with_three_usage_rows(committed) -> None:
    conn = committed
    job_id = _seed(conn)
    run_id = _enqueue(conn, job_id)
    conn.commit()

    execute_run(FakeResumeWriter(passes_on_attempt=4), FakeFitScorer(), run_id)

    conn.commit()
    stored = repo.get_run(conn, run_id)
    assert stored is not None and stored["status"] == "below_baseline"
    assert repo.artifact(conn, run_id) is not None
    assert len(repo.usage_for_run(conn, run_id)) == 3


def test_cost_cap_stops_further_attempts(committed, monkeypatch) -> None:
    monkeypatch.setenv("RESUME_MAX_COST_USD", "0.01")
    conn = committed
    job_id = _seed(conn)
    run_id = _enqueue(conn, job_id)
    conn.commit()

    execute_run(FakeResumeWriter(passes_on_attempt=4), FakeFitScorer(), run_id)

    conn.commit()
    stored = repo.get_run(conn, run_id)
    assert stored is not None and stored["status"] == "below_baseline"
    assert len(repo.usage_for_run(conn, run_id)) == 1


def test_fail_mode_stores_no_pdf(committed, monkeypatch) -> None:
    monkeypatch.setenv("RESUME_GATE", "fail")
    conn = committed
    job_id = _seed(conn)
    run_id = _enqueue(conn, job_id)
    conn.commit()

    execute_run(FakeResumeWriter(passes_on_attempt=4), FakeFitScorer(), run_id)

    conn.commit()
    stored = repo.get_run(conn, run_id)
    assert stored is not None and stored["status"] == "failed"
    assert repo.artifact(conn, run_id) is None

"""Run one resume at a time. Wakes on NOTIFY, and polls every 30 seconds as a fallback."""

import os
import shutil
import tempfile
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from jobhunt.core.db import pool, tx
from jobhunt.core.settings import load_settings
from jobhunt.fit.base import FitScorer
from jobhunt.fit.sources import bank_docs
from jobhunt.jobs import queries
from jobhunt.resume import repo
from jobhunt.resume.base import ResumeDraft, ResumeRequest, ResumeWriter
from jobhunt.resume.filler import rank_filler
from jobhunt.resume.gate import GateResult, cited_ids, covered_aspects, evaluate

_RETRIES = 2
_LISTEN_SECONDS = 30


class StopRequested(Exception):
    """Raised between attempts when the process was asked to shut down."""


def max_cost() -> Decimal:
    raw = os.environ.get("RESUME_MAX_COST_USD", "5")
    try:
        return Decimal(raw)
    except Exception:
        return Decimal(5)


def gate_mode() -> str:
    return "fail" if os.environ.get("RESUME_GATE") == "fail" else "warn"


def execute_run(agent: ResumeWriter, model: FitScorer, run_id: int) -> None:
    """Generate one claimed run, committing after every attempt."""
    conn = pool().getconn()
    stop = threading.Event()
    beater = threading.Thread(target=_heartbeat, args=(run_id, stop), daemon=True)
    beater.start()
    try:
        _execute(conn, agent, model, run_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        stop.set()
        beater.join(timeout=1)
        pool().putconn(conn)


def serve(agent: ResumeWriter, model: FitScorer, *, handle_signals: bool = True) -> None:
    """Listen for new runs until stopped. One run at a time."""
    import signal

    if handle_signals:
        signal.signal(signal.SIGTERM, lambda *_args: request_stop())
    url = load_settings().database_url.get_secret_value()
    with psycopg.connect(url, autocommit=True) as listener:
        listener.execute("LISTEN resume_runs")
        while not _stopping():
            claimed = _claim()
            if claimed is not None:
                execute_run(agent, model, int(claimed["id"]))
                continue
            _wait(listener)


def request_stop() -> None:
    _stopping_flag.requested = True


class _StopFlag:
    def __init__(self) -> None:
        self.requested = False

    def __call__(self) -> bool:
        return self.requested


_stopping_flag = _StopFlag()


def _stopping() -> bool:
    return _stopping_flag()


def _score_shortlist(
    conn: Any, model: FitScorer, job: dict[str, Any], run_id: int
) -> dict[str, Any]:
    """Score one job that has a fit row but no shortlist, then reload it."""
    from jobhunt.fit import repo as fit_repo
    from jobhunt.fit.runner import score_batch
    from jobhunt.fit.sources import resolve

    source_hash, docs, _resume_id = resolve(conn, "bank", model)
    score_batch(
        conn,
        model,
        docs,
        source_hash,
        [{"id": job["id"], "title": job["title"], "description_md": job["description_md"]}],
    )
    fit_repo.mark_source_scored(conn, source_hash)
    repo.set_fit_source(conn, run_id, model.model_id, source_hash)
    conn.commit()
    repo.add_event(conn, run_id, "log", {"message": "scored the shortlist"})
    refreshed = queries.get_job(conn, int(job["id"]), "bank")
    return refreshed or job


def _execute(conn: Any, agent: ResumeWriter, model: FitScorer, run_id: int) -> None:
    run = repo.get_run(conn, run_id)
    if run is None:
        return
    job_id = int(run["job_id"])
    job = queries.get_job(conn, job_id, "bank")
    if job is None or not job.get("description_md"):
        _fail(conn, run_id, "job has no description")
        return
    if not job.get("top_brags"):
        job = _score_shortlist(conn, model, job, run_id)
    matches = list(job.get("top_brags") or [])
    if not matches:
        _fail(conn, run_id, "job has no fit matches")
        return

    docs = bank_docs(conn)
    by_id = {doc.id: doc for doc in docs}
    shortlist = [by_id[item["id"]] for item in matches if item["id"] in by_id]
    if not shortlist:
        _fail(conn, run_id, "shortlisted brag docs are not in the bank")
        return
    impacts = _impacts(conn)
    filler = rank_filler(
        model, docs, {doc.id for doc in shortlist}, impacts, str(job["description_md"])
    )
    aspects = {str(item["id"]): str(item["aspect"]) for item in matches}
    baseline_score = float(job["score"] or 0)
    baseline_coverage = None if job.get("coverage") is None else float(job["coverage"])
    profile = next((doc.text for doc in docs if doc.id == "profile"), "")

    workdir = Path(tempfile.mkdtemp(prefix=f"resume-{run_id}-"))
    draft: ResumeDraft | None = None
    gate: GateResult | None = None
    best_draft: ResumeDraft | None = None
    best_gate: GateResult | None = None
    feedback: list[str] = []
    attempts = 0
    try:
        for attempt in range(1, _RETRIES + 2):
            if _stopping():
                repo.requeue(conn, run_id)
                repo.add_event(conn, run_id, "status", {"status": "queued"})
                return
            if attempt > 1 and repo.cost_for_run(conn, run_id) >= max_cost():
                repo.add_event(conn, run_id, "log", {"message": "cost cap reached"})
                break
            repo.add_event(conn, run_id, "progress", {"stage": "generating", "attempt": attempt})
            request = ResumeRequest(
                job_id=job_id,
                job_description=str(job["description_md"]),
                shortlist=shortlist,
                filler=filler,
                profile=profile,
                aspects=aspects,
                feedback=feedback,
            )
            try:
                draft = agent.generate(request, workdir)
            except Exception as exc:
                _record_failure_usage(conn, run_id, attempt, agent, str(run["model"]))
                _fail(conn, run_id, str(exc))
                return
            attempts = attempt
            _record(conn, run_id, attempt, agent.agent_id, draft)
            conn.commit()
            gate = evaluate(
                model,
                request.job_description,
                draft.resume_json,
                shortlist_ids={doc.id for doc in shortlist},
                covered_aspects=covered_aspects(matches),
                baseline_score=baseline_score,
                baseline_model_id=str(job.get("fit_model_id") or ""),
            )
            if gate.passed:
                break
            # A rewrite that scores lower is discarded. Another pass keeps dropping terms.
            if best_gate is not None and gate.resume_score < best_gate.resume_score:
                draft = best_draft
                gate = best_gate
                repo.add_event(
                    conn,
                    run_id,
                    "log",
                    {"stage": "gating", "message": "kept the higher-scoring draft"},
                )
                conn.commit()
                break
            best_draft = draft
            best_gate = gate
            feedback = gate.feedback
            repo.add_event(
                conn,
                run_id,
                "log",
                {
                    "stage": "gating",
                    "passed": False,
                    "lost": gate.lost_aspects,
                    "resume_score": gate.resume_score,
                    "baseline": baseline_score,
                },
            )
            conn.commit()
        if draft is None or gate is None:
            _fail(conn, run_id, "no resume was produced")
            return
        shortlist_ids = {doc.id for doc in shortlist}
        used_filler = [
            doc_id for doc_id in cited_ids(draft.resume_json) if doc_id not in shortlist_ids
        ]
        _store(
            conn,
            run,
            draft,
            gate,
            baseline_score,
            baseline_coverage,
            used_filler,
            attempts,
            job,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _store(
    conn: Any,
    run: dict[str, Any],
    draft: ResumeDraft,
    gate: GateResult,
    baseline_score: float,
    baseline_coverage: float | None,
    filler_ids: list[str],
    attempts: int,
    job: dict[str, Any],
) -> None:
    run_id = int(run["id"])
    keep_pdf = gate.passed or gate_mode() == "warn"
    status = "ok" if gate.passed else "below_baseline"
    if not gate.passed and gate_mode() == "fail":
        status = "failed"
    if keep_pdf:
        repo.save_artifact(
            conn,
            run_id,
            pdf=draft.pdf,
            resume_json=draft.resume_json,
            lint_report=draft.lint_report,
        )
    repo.finish(
        conn,
        run_id,
        status=status,
        baseline_score=baseline_score,
        baseline_coverage=baseline_coverage,
        resume_score=None if gate.skipped else gate.resume_score,
        resume_coverage=None if gate.skipped else gate.resume_coverage,
        lost_aspects=gate.lost_aspects,
        filler_ids=filler_ids,
        attempts=attempts,
        error=None if status != "failed" else "resume scored below the shortlist",
    )
    repo.add_event(
        conn,
        run_id,
        "status",
        {
            "status": status,
            "resume_score": gate.resume_score,
            "baseline_score": baseline_score,
            "lost": gate.lost_aspects,
            "filler": filler_ids,
            "company": job.get("company"),
            "title": job.get("title"),
        },
    )


def _record(conn: Any, run_id: int, attempt: int, agent_id: str, draft: ResumeDraft) -> None:
    usage = draft.usage
    repo.record_usage(
        conn,
        run_id,
        attempt,
        {
            "agent_id": agent_id,
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "num_turns": usage.num_turns,
            "duration_ms": usage.duration_ms,
            "cost_usd": usage.cost_usd,
            "cost_source": usage.cost_source,
        },
    )


def _record_failure_usage(
    conn: Any, run_id: int, attempt: int, agent: ResumeWriter, model: str
) -> None:
    repo.record_usage(
        conn,
        run_id,
        attempt,
        {
            "agent_id": agent.agent_id,
            "model": model,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "num_turns": 0,
            "duration_ms": 0,
            "cost_usd": Decimal(0),
            "cost_source": "computed",
        },
    )


def _fail(conn: Any, run_id: int, message: str) -> None:
    repo.finish(
        conn,
        run_id,
        status="failed",
        baseline_score=None,
        baseline_coverage=None,
        resume_score=None,
        resume_coverage=None,
        lost_aspects=[],
        filler_ids=[],
        attempts=0,
        error=message,
    )
    repo.add_event(conn, run_id, "status", {"status": "failed", "error": message})


def _impacts(conn: Any) -> dict[str, int | None]:
    from jobhunt.brag import repo as brag_repo

    impacts: dict[str, int | None] = {}
    for doc in brag_repo.list_brag_docs(conn):
        raw = doc.get("impact")
        impacts[str(doc["id"])] = raw if isinstance(raw, int) else None
    return impacts


def _heartbeat(run_id: int, stop: threading.Event) -> None:
    while not stop.wait(60):
        try:
            with tx() as conn:
                repo.extend_lease(conn, run_id)
        except Exception:
            return


def _claim() -> dict[str, Any] | None:
    conn = pool().getconn()
    try:
        claimed = repo.claim(conn)
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()
        raise
    finally:
        pool().putconn(conn)


def _wait(listener: psycopg.Connection[tuple[object, ...]]) -> None:
    try:
        for _notice in listener.notifies(timeout=_LISTEN_SECONDS):
            return
    except psycopg.errors.QueryCanceled:
        return

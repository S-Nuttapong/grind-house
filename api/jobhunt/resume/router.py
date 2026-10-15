"""Queue a resume, stream its progress, and download the PDF. No agent runs in the request."""

import json
import re
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any, NoReturn

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from jobhunt import composition
from jobhunt.composition import require_on_machine
from jobhunt.core.db import tx
from jobhunt.core.settings import load_settings
from jobhunt.jobs import queries
from jobhunt.resume import repo

router = APIRouter(prefix="/api")
_FILENAME = re.compile(r"[^A-Za-z0-9]+")


class BulkResumeIn(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=300)


@router.post("/jobs/{job_id}/resume", status_code=202)
def enqueue_resume(job_id: int) -> dict[str, int]:
    _ensure_writer()
    with tx() as conn:
        run_id, reason = _queue_one(conn, job_id, skip_finished=False)
    if run_id is None:
        _reject(reason or "could not queue")
    return {"run_id": run_id}


@router.post("/resume-runs/bulk")
def enqueue_resumes(body: BulkResumeIn) -> dict[str, list[dict[str, Any]]]:
    _ensure_writer()
    queued: list[dict[str, int]] = []
    skipped: list[dict[str, Any]] = []
    with tx() as conn:
        for job_id in dict.fromkeys(body.job_ids):
            run_id, reason = _queue_one(conn, job_id, skip_finished=True)
            if run_id is None:
                skipped.append({"job_id": job_id, "reason": reason or "could not queue"})
            else:
                queued.append({"job_id": job_id, "run_id": run_id})
    return {"queued": queued, "skipped": skipped}


@router.get("/resume-queue")
def resume_queue() -> dict[str, list[dict[str, Any]]]:
    with tx() as conn:
        snapshot = repo.queue_snapshot(conn)
    return {name: [_public(row) for row in rows] for name, rows in snapshot.items()}


@router.get("/jobs/{job_id}/resume-runs")
def list_resume_runs(job_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        if queries.get_job(conn, job_id, "bank") is None:
            raise HTTPException(status_code=404, detail="no such job")
        return [_public(row) for row in repo.list_for_job(conn, job_id)]


@router.get("/resume-runs/{run_id}")
def get_resume_run(run_id: int) -> dict[str, Any]:
    with tx() as conn:
        run = repo.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="no such run")
        public = _public(run)
        ahead = repo.queued_ahead(conn, run_id)
        if ahead is not None:
            public["ahead"] = ahead
        return public


@router.get("/resume-runs/{run_id}/stream")
async def stream_resume_run(run_id: int, request: Request) -> StreamingResponse:
    last_id = int(request.headers.get("last-event-id") or 0)

    async def events() -> AsyncIterator[str]:
        sent = last_id
        url = load_settings().database_url.get_secret_value()
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
            await conn.execute(f"LISTEN resume_run_{int(run_id)}")
            for event in _replay(run_id, sent):
                sent = int(event["id"])
                yield _sse(event)
                if event["kind"] == "status":
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    async for _notice in conn.notifies(timeout=15):
                        for event in _replay(run_id, sent):
                            sent = int(event["id"])
                            yield _sse(event)
                            if event["kind"] == "status":
                                return
                        break
                except psycopg.errors.QueryCanceled:
                    yield "event: ping\ndata: {}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/resume-runs/{run_id}/pdf")
def download_pdf(run_id: int) -> Response:
    with tx() as conn:
        run = repo.get_run(conn, run_id)
        stored = repo.artifact(conn, run_id)
        if run is None or stored is None:
            raise HTTPException(status_code=404, detail="no pdf for this run")
        job = queries.get_job(conn, int(run["job_id"]), "bank")
    company = str(job["company"]) if job else "Company"
    title = str(job["title"]) if job else "Role"
    year = date.today().year
    filename = f"{_slug(company)}-{_slug(title)}-{year}.pdf"
    pdf = stored["pdf"]
    body = pdf.tobytes() if isinstance(pdf, memoryview) else bytes(pdf)
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/usage")
def admin_usage(days: int = 30) -> dict[str, Any]:
    window = min(max(days, 1), 365)
    with tx() as conn:
        summary = repo.usage_summary(conn, days=window)
    return _money(summary)


def _ensure_writer() -> None:
    try:
        require_on_machine(composition.COMPOSITION.writer, "resume writer")
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _queue_one(conn: Any, job_id: int, *, skip_finished: bool) -> tuple[int | None, str | None]:
    """Queue one job. Returns (run id, None) or (None, reason)."""
    job = queries.get_job(conn, job_id, "bank")
    if job is None:
        return None, "no such job"
    if not job.get("description_md"):
        return None, "job has no description"
    # Older scores have no shortlist rows. The worker fills those in before it writes.
    if not job.get("top_brags") and (not job.get("fit_model_id") or not job.get("fit_source")):
        return None, "score this job before generating a resume"
    latest = repo.latest_status(conn, job_id)
    if skip_finished and latest in {"queued", "running"}:
        return None, "in queue"
    if skip_finished and latest in {"ok", "below_baseline"}:
        return None, "already generated"
    agent = composition.COMPOSITION.writer
    run_id, _created = repo.enqueue(
        conn,
        job_id=job_id,
        agent_id=agent.agent_id,
        model=_model_name(),
        fit_model_id=str(job["fit_model_id"]),
        fit_source_hash=str(job["fit_source"]),
    )
    return run_id, None


def _reject(reason: str) -> NoReturn:
    status = 404 if reason == "no such job" else 409
    raise HTTPException(status_code=status, detail=reason)


def _model_name() -> str:
    import os

    return os.environ.get("RESUME_MODEL", "claude-opus-5-5")


def _replay(run_id: int, after_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return repo.events_after(conn, run_id, after_id)


def _sse(event: dict[str, Any]) -> str:
    payload = json.dumps({"kind": event["kind"], **event["payload"]})
    return f"id: {event['id']}\ndata: {payload}\n\n"


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _jsonable(value) for key, value in row.items()}


def _money(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "days": summary["days"],
        "runs": summary["runs"],
        "cost_usd": _jsonable(summary["cost_usd"]),
        "input_tokens": summary["input_tokens"],
        "output_tokens": summary["output_tokens"],
        "by_day": [_public(row) for row in summary["by_day"]],
        "recent": [_public(row) for row in summary["recent"]],
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _slug(value: str) -> str:
    cleaned = _FILENAME.sub("-", value).strip("-")
    return cleaned or "resume"

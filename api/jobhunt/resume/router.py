"""Queue a resume, stream its progress, and download the PDF. No agent runs in the request."""

import json
import re
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from jobhunt.core.db import tx
from jobhunt.core.settings import load_settings
from jobhunt.jobs import queries
from jobhunt.resume import repo
from jobhunt.resume.registry import create

router = APIRouter(prefix="/api")
_FILENAME = re.compile(r"[^A-Za-z0-9]+")


@router.post("/jobs/{job_id}/resume", status_code=202)
def enqueue_resume(job_id: int) -> dict[str, int]:
    with tx() as conn:
        job = queries.get_job(conn, job_id, "bank")
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        if not job.get("description_md"):
            raise HTTPException(status_code=409, detail="job has no description")
        # Older scores have no shortlist rows. The worker fills those in before it writes.
        if not job.get("top_brags") and (not job.get("fit_model_id") or not job.get("fit_source")):
            raise HTTPException(status_code=409, detail="score this job before generating a resume")
        try:
            agent = create()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        run_id, _created = repo.enqueue(
            conn,
            job_id=job_id,
            agent_id=agent.agent_id,
            model=_model_name(),
            fit_model_id=str(job["fit_model_id"]),
            fit_source_hash=str(job["fit_source"]),
        )
    return {"run_id": run_id}


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
        return _public(run)


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


def _model_name() -> str:
    import os

    return os.environ.get("RESUME_MODEL", "claude-haiku-5-5")


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

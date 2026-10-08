"""Profile, resume, and fit-schedule routes. None of these run the model."""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from jobhunt.db import fit_repo, tx
from jobhunt.fit.schedule import describe, next_runs, validate

router = APIRouter(prefix="/api")

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_UPLOAD_SUFFIXES = {".pdf", ".md", ".txt", ".json"}
Mode = Literal["bank", "resume"]


class EntryIn(BaseModel):
    id: str
    title: str
    company: str | None = None
    role: str | None = None
    period: str | None = None
    my_role: str | None = None
    scope: str | None = None
    metrics: list[dict[str, Any]] = []
    strength: int | None = None
    confidential: bool = False
    status: str = "draft"
    tags: list[str] = []
    body_md: str = ""


class ProfileIn(BaseModel):
    body_md: str


class ScheduleIn(BaseModel):
    name: str
    mode: Mode
    cron: str
    timezone: str = "Asia/Bangkok"
    enabled: bool = True


def _checked(schedule: ScheduleIn) -> None:
    problems = validate(schedule.cron, schedule.timezone)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))


@router.get("/profile/entries")
def list_entries() -> list[dict[str, Any]]:
    with tx() as conn:
        return fit_repo.list_bank_entries(conn)


@router.post("/profile/entries", status_code=201)
def create_entry(entry: EntryIn) -> dict[str, Any]:
    with tx() as conn:
        fit_repo.upsert_bank_entry(conn, {**entry.model_dump(), "origin": "ui"})
        stored = fit_repo.get_bank_entry(conn, entry.id)
    if stored is None:
        raise HTTPException(status_code=500, detail="entry was not stored")
    return stored


@router.put("/profile/entries/{entry_id}")
def update_entry(entry_id: str, entry: EntryIn) -> dict[str, Any]:
    entry.id = entry_id
    return create_entry(entry)


@router.delete("/profile/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: str) -> None:
    with tx() as conn:
        if not fit_repo.delete_bank_entry(conn, entry_id):
            raise HTTPException(status_code=404, detail="no such entry")


@router.get("/profile/summary")
def get_summary() -> dict[str, str]:
    with tx() as conn:
        return {"body_md": fit_repo.get_bank_profile(conn)}


@router.put("/profile/summary")
def put_summary(body: ProfileIn) -> dict[str, str]:
    with tx() as conn:
        fit_repo.set_bank_profile(conn, body.body_md)
    return {"body_md": body.body_md}


@router.get("/resumes")
def list_resumes() -> list[dict[str, Any]]:
    with tx() as conn:
        return fit_repo.list_resumes(conn)


@router.post("/resumes", status_code=201)
async def upload_resume(file: UploadFile) -> dict[str, Any]:
    name = file.filename or "resume"
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in _UPLOAD_SUFFIXES:
        raise HTTPException(status_code=422, detail="upload a .pdf, .md, .txt, or .json file")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file is over 5 MB")
    text = _extract(name, content)
    with tx() as conn:
        resume_id = fit_repo.insert_resume(
            conn, name=name, text=text, filename=name, origin="upload"
        )
        stored = fit_repo.get_resume(conn, resume_id)
    if stored is None:
        raise HTTPException(status_code=500, detail="resume was not stored")
    return stored


@router.post("/resumes/{resume_id}/select")
def select_resume(resume_id: int) -> dict[str, Any]:
    with tx() as conn:
        if not fit_repo.select_resume(conn, resume_id):
            raise HTTPException(status_code=404, detail="no such resume")
        stored = fit_repo.get_resume(conn, resume_id)
    return stored or {}


@router.delete("/resumes/{resume_id}", status_code=204)
def delete_resume(resume_id: int) -> None:
    with tx() as conn:
        if not fit_repo.delete_resume(conn, resume_id):
            raise HTTPException(status_code=404, detail="no such resume")


def _schedule_view(row: dict[str, Any]) -> dict[str, Any]:
    row["description"] = describe(row["cron"])
    row["upcoming"] = [moment.isoformat() for moment in next_runs(row["cron"], row["timezone"])]
    return row


@router.get("/fit/schedules")
def list_schedules() -> list[dict[str, Any]]:
    with tx() as conn:
        return [_schedule_view(row) for row in fit_repo.list_schedules(conn)]


@router.post("/fit/schedules", status_code=201)
def create_schedule(schedule: ScheduleIn) -> dict[str, Any]:
    _checked(schedule)
    with tx() as conn:
        schedule_id = fit_repo.insert_schedule(
            conn,
            {
                **schedule.model_dump(),
                "next_run_at": next_runs(schedule.cron, schedule.timezone, 1)[0],
            },
        )
        stored = fit_repo.get_schedule(conn, schedule_id)
    return _schedule_view(stored or {})


@router.put("/fit/schedules/{schedule_id}")
def update_schedule(schedule_id: int, schedule: ScheduleIn) -> dict[str, Any]:
    _checked(schedule)
    with tx() as conn:
        fields = {
            **schedule.model_dump(),
            "next_run_at": next_runs(schedule.cron, schedule.timezone, 1)[0],
        }
        if not fit_repo.update_schedule(conn, schedule_id, fields):
            raise HTTPException(status_code=404, detail="no such schedule")
        stored = fit_repo.get_schedule(conn, schedule_id)
    return _schedule_view(stored or {})


@router.delete("/fit/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int) -> None:
    with tx() as conn:
        if not fit_repo.delete_schedule(conn, schedule_id):
            raise HTTPException(status_code=404, detail="no such schedule")


@router.post("/fit/schedules/{schedule_id}/run", status_code=202)
def run_schedule(schedule_id: int) -> dict[str, Any]:
    """Queue a run and return at once. The fit worker scores it in the background."""
    from jobhunt.fit.worker import idempotency_key

    with tx() as conn:
        schedule = fit_repo.get_schedule(conn, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail="no such schedule")
        slot = datetime.now().strftime("%Y-%m-%dT%H:%M")
        run_id, created = fit_repo.enqueue_run(
            conn,
            {
                "schedule_id": schedule_id,
                "mode": schedule["mode"],
                "trigger": "manual",
                "model_id": "pending",
                "idempotency_key": idempotency_key(schedule["mode"], "manual", slot, schedule_id),
            },
        )
    return {"run_id": run_id, "created": created}


@router.get("/fit/runs")
def list_runs() -> list[dict[str, Any]]:
    with tx() as conn:
        return fit_repo.list_runs(conn)


@router.get("/fit/runs/{run_id}")
def get_run(run_id: int) -> dict[str, Any]:
    with tx() as conn:
        run = fit_repo.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="no such run")
        run["progress"] = fit_repo.latest_progress(conn, run_id)
    return run


@router.get("/fit/runs/{run_id}/stream")
async def stream_run(run_id: int, request: Request) -> StreamingResponse:
    """Replay the run's events, then follow new ones until it finishes.

    Listening starts before the replay, so an event can't land between them.
    `Last-Event-ID` resumes a reconnect without repeating events.
    """
    from jobhunt.settings import load_settings

    last_id = int(request.headers.get("last-event-id") or 0)

    async def events() -> AsyncIterator[str]:
        sent = last_id
        url = load_settings().database_url.get_secret_value()
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
            await conn.execute(f"LISTEN fit_run_{int(run_id)}")
            for event in _replay(run_id, sent):
                sent = int(event["id"])
                yield _sse(event)
                if _is_final(event):
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    async for _notice in conn.notifies(timeout=15):
                        for event in _replay(run_id, sent):
                            sent = int(event["id"])
                            yield _sse(event)
                            if _is_final(event):
                                return
                        break
                except psycopg.errors.QueryCanceled:
                    yield "event: ping\ndata: {}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _replay(run_id: int, after_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return fit_repo.run_events_after(conn, run_id, after_id)


def _sse(event: dict[str, Any]) -> str:
    payload = json.dumps({"kind": event["kind"], **event["payload"]})
    return f"id: {event['id']}\ndata: {payload}\n\n"


def _is_final(event: dict[str, Any]) -> bool:
    return bool(event["kind"] == "status")


@router.get("/fit/status")
def fit_status() -> dict[str, Any]:
    with tx() as conn:
        worker = fit_repo.worker_status(conn)
        modes = {}
        for mode in ("bank", "resume"):
            source = fit_repo.latest_scored_source(conn, mode)
            modes[mode] = {"source_hash": source, "stale": _is_stale(conn, mode, source)}
    return {"worker": worker, "modes": modes}


def _is_stale(conn: Any, mode: str, scored_hash: str | None) -> bool:
    """True when the profile changed after the last finished run."""
    import hashlib

    from jobhunt.fit.sources import SourceError, bank_text, resume_text

    try:
        if mode == "bank":
            text = bank_text(conn, include_confidential=True)
        else:
            text = resume_text(conn)[0]
    except SourceError:
        return False
    profile = str(text)
    if not profile.strip():
        return False
    return hashlib.sha256(profile.encode()).hexdigest() != scored_hash


def _extract(name: str, content: bytes) -> str:
    if name.lower().endswith(".pdf"):
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    return content.decode("utf-8", errors="replace").strip()

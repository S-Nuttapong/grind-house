"""Fit schedule, run, and status routes. None of these run the model in the request."""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from jobhunt.core.db import tx
from jobhunt.fit import repo as fit_repo
from jobhunt.fit.schedule import describe, next_runs, validate

router = APIRouter(prefix="/api")


Mode = Literal["bank", "resume"]


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


def _schedule_view(row: dict[str, Any], last_run: dict[str, Any] | None = None) -> dict[str, Any]:
    row["description"] = describe(row["cron"])
    row["upcoming"] = [moment.isoformat() for moment in next_runs(row["cron"], row["timezone"])]
    row["last_run"] = last_run
    return row


@router.get("/fit/schedules")
def list_schedules() -> list[dict[str, Any]]:
    with tx() as conn:
        latest = fit_repo.latest_run_by_schedule(conn)
        schedules = fit_repo.list_schedules(conn)
        return [_schedule_view(row, latest.get(int(row["id"]))) for row in schedules]


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
    from jobhunt.core.settings import load_settings

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
    from jobhunt.fit.sources import SourceError, current_docs, docs_hash

    try:
        docs = current_docs(conn, mode)
    except SourceError:
        return False
    return docs_hash(docs) != scored_hash

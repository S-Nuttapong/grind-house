"""JSON API for the Next.js board. Response models are the contract in /openapi.json."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_serializer

from jobhunt.db import tx
from jobhunt.web import board

router = APIRouter(prefix="/api")

Status = Literal["saved", "skipped", "applied"]


class JobSummary(BaseModel):
    id: int
    title: str
    company: str
    city: str | None
    country: str | None
    place: str
    remote: str | None
    remote_label: str
    employment_type: str | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_label: str | None
    posted_at: date | None
    first_seen_at: datetime
    closed_at: datetime | None
    age: str
    is_new: bool
    apply_url: str
    status: str | None
    score: int | None
    band: str | None
    stage: str
    snippet: str
    sources: list[str]

    @field_serializer("salary_min", "salary_max")
    def _money(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class Posting(BaseModel):
    source_id: str
    source_url: str | None


class JobEvent(BaseModel):
    status: str
    reason: str | None
    note: str | None
    origin: str
    at: datetime


class JobDetail(JobSummary):
    description_md: str | None
    postings: list[Posting]
    events: list[JobEvent]
    tailor_prompt: str


class JobPage(BaseModel):
    jobs: list[JobSummary]
    total: int
    page: int
    pages: int
    page_size: int


class EventIn(BaseModel):
    status: Status
    reason: str | None = None


class Facets(BaseModel):
    sources: list[str]
    remote: list[str]


class Pipeline(BaseModel):
    saved: list[JobSummary]
    applied: list[JobSummary]
    skipped: list[JobSummary]


class Run(BaseModel):
    id: int
    source_id: str
    scope_name: str | None
    status: str
    fetched: int | None
    new_jobs: int | None
    updated: int | None
    closed: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


@router.get("/jobs", response_model=JobPage)
def list_jobs(request: Request) -> JobPage:
    filters = board.parse_filters(dict(request.query_params))
    with tx() as conn:
        rows, total = board.list_jobs(conn, filters)
    return JobPage(
        jobs=[_summary(row) for row in rows],
        total=total,
        page=int(filters["page"]),
        pages=max(1, (total + board.PAGE_SIZE - 1) // board.PAGE_SIZE),
        page_size=board.PAGE_SIZE,
    )


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: int) -> JobDetail:
    with tx() as conn:
        job = board.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _detail(job)


@router.post("/jobs/{job_id}/events", response_model=JobDetail)
def record_event(job_id: int, event: EventIn) -> JobDetail:
    reason = (event.reason or "").strip() or None
    with tx() as conn:
        if board.get_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        board.record_event(conn, job_id, event.status, reason)
        job = board.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _detail(job)


@router.get("/facets", response_model=Facets)
def facets() -> Facets:
    with tx() as conn:
        return Facets(**board.list_facets(conn))


@router.get("/pipeline", response_model=Pipeline)
def pipeline() -> Pipeline:
    with tx() as conn:
        columns = board.list_pipeline(conn)
    return Pipeline(**{name: [_summary(row) for row in rows] for name, rows in columns.items()})


@router.get("/runs", response_model=list[Run])
def runs() -> list[Run]:
    with tx() as conn:
        return [Run(**row) for row in board.list_runs(conn)]


def _summary(row: dict[str, Any]) -> JobSummary:
    return JobSummary(**_shared(row))


def _detail(row: dict[str, Any]) -> JobDetail:
    return JobDetail(
        **_shared(row),
        description_md=row.get("description_md"),
        postings=[Posting(**item) for item in row["postings"]],
        events=[JobEvent(**item) for item in row["events"]],
        tailor_prompt=row["tailor_prompt"],
    )


def _shared(row: dict[str, Any]) -> dict[str, Any]:
    fields = set(JobSummary.model_fields) - {"sources"}
    shared = {name: row.get(name) for name in fields}
    shared["sources"] = row["source_list"]
    shared["snippet"] = row.get("snippet") or ""
    return shared

"""JSON API for the Next.js board. Response models are the contract in /openapi.json."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_serializer

from jobhunt.core.db import tx
from jobhunt.jobs import queries

router = APIRouter(prefix="/api")

Status = Literal["saved", "skipped", "applied", "removed"]


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
    experience_label: str | None = None
    posted_at: date | None
    first_seen_at: datetime
    closed_at: datetime | None
    age: str
    is_new: bool
    apply_url: str
    status: str | None
    score: float | None
    band: str | None
    fit_tier: str | None
    matched_terms: list[str]
    missing_terms: list[str]
    stage: str
    snippet: str
    sources: list[str]
    resume_status: str | None = None

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


class TopBrag(BaseModel):
    id: str
    title: str
    aspect: str
    similarity: float


class JobDetail(JobSummary):
    description_md: str | None
    postings: list[Posting]
    events: list[JobEvent]
    tailor_prompt: str
    coverage: float | None = None
    gaps: list[str] = []
    top_brags: list[TopBrag] = []


class JobPage(BaseModel):
    jobs: list[JobSummary]
    total: int
    page: int
    pages: int
    page_size: int


class EventIn(BaseModel):
    status: Status
    reason: str | None = None


class BulkEventsIn(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=300)
    status: Status
    reason: str | None = None


class PipelineOrderIn(BaseModel):
    saved: list[int] = Field(default_factory=list, max_length=300)
    applied: list[int] = Field(default_factory=list, max_length=300)
    skipped: list[int] = Field(default_factory=list, max_length=300)


class Facets(BaseModel):
    sources: list[str]
    remote: list[str]
    countries: list[str]
    regions: list[str]
    roles: list[str]
    industries: list[str]
    levels: list[str]


class Pipeline(BaseModel):
    saved: list[JobSummary]
    applied: list[JobSummary]
    skipped: list[JobSummary]


@router.get("/jobs", response_model=JobPage)
def list_jobs(request: Request) -> JobPage:
    filters = queries.parse_filters(dict(request.query_params))
    with tx() as conn:
        rows, total = queries.list_jobs(conn, filters)
    return JobPage(
        jobs=[_summary(row) for row in rows],
        total=total,
        page=int(filters["page"]),
        pages=max(1, (total + queries.PAGE_SIZE - 1) // queries.PAGE_SIZE),
        page_size=queries.PAGE_SIZE,
    )


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: int, fit: str = "bank") -> JobDetail:
    with tx() as conn:
        job = queries.get_job(conn, job_id, fit if fit in {"bank", "resume"} else "bank")
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _detail(job)


@router.post("/jobs/events/bulk")
def record_events(event: BulkEventsIn) -> dict[str, list[int]]:
    reason = (event.reason or "").strip() or None
    with tx() as conn:
        updated = queries.record_events(conn, event.job_ids, event.status, reason)
    return {"updated": updated}


@router.post("/jobs/{job_id}/events", response_model=JobDetail)
def record_event(job_id: int, event: EventIn) -> JobDetail:
    reason = (event.reason or "").strip() or None
    with tx() as conn:
        if queries.get_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        queries.record_event(conn, job_id, event.status, reason)
        job = queries.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _detail(job)


@router.get("/facets", response_model=Facets)
def facets() -> Facets:
    with tx() as conn:
        return Facets(**queries.list_facets(conn))


@router.post("/pipeline/order")
def pipeline_order(body: PipelineOrderIn) -> dict[str, bool]:
    columns = {"saved": body.saved, "applied": body.applied, "skipped": body.skipped}
    if sum(len(ids) for ids in columns.values()) > 300:
        raise HTTPException(status_code=422, detail="too many jobs")
    with tx() as conn:
        queries.arrange_pipeline(conn, columns)
    return {"ok": True}


@router.get("/pipeline", response_model=Pipeline)
def pipeline() -> Pipeline:
    with tx() as conn:
        columns = queries.list_pipeline(conn)
    return Pipeline(**{name: [_summary(row) for row in rows] for name, rows in columns.items()})


def _summary(row: dict[str, Any]) -> JobSummary:
    return JobSummary(**_shared(row))


def _detail(row: dict[str, Any]) -> JobDetail:
    return JobDetail(
        **_shared(row),
        description_md=row.get("description_md"),
        postings=[Posting(**item) for item in row["postings"]],
        events=[JobEvent(**item) for item in row["events"]],
        tailor_prompt=row["tailor_prompt"],
        coverage=row.get("coverage"),
        gaps=list(row.get("gaps") or []),
        top_brags=[TopBrag(**item) for item in row.get("top_brags") or []],
    )


def _shared(row: dict[str, Any]) -> dict[str, Any]:
    fields = set(JobSummary.model_fields) - {"sources"}
    shared = {name: row.get(name) for name in fields}
    shared["sources"] = row["source_list"]
    shared["snippet"] = row.get("snippet") or ""
    return shared

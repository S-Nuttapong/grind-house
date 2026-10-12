"""Adapter types. Fetch I/O stays at the edge; mapping is pure."""

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from jobhunt.core.http import HttpClient
from jobhunt.facts.base import JobDetail


class RawPosting(BaseModel):
    source_id: str
    source_job_id: str
    source_url: str
    apply_url: str | None = None
    company_name: str
    company_hint: dict[str, Any] = Field(default_factory=dict)
    title: str
    location_raw: str | None = None
    remote_hint: str | None = None
    description_html: str | None = None
    description_text: str | None = None
    posted_at: date | None = None
    employment_type_raw: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_interval_raw: str | None = None
    level_hint: str | None = None
    role_hint: str | None = None
    industry_hint: str | None = None
    payload: dict[str, Any]


class CompanyTarget(BaseModel):
    id: int
    name: str
    ats_slug: str
    tier: str | None = None


class ScopeView(BaseModel):
    id: int
    source_id: str
    params: dict[str, Any]


class FetchContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    http: HttpClient
    companies: list[CompanyTarget]


class FetchBatch(BaseModel):
    company_id: int | None = None
    postings: list[RawPosting] = Field(default_factory=list)
    failed: bool = False
    clear_ats: bool = False
    resume_page: int | None = None


class SourceSpec(BaseModel):
    """The sources-table row this adapter owns. enabled is not part of it."""

    kind: Literal["ats", "aggregator", "feed"]
    min_interval: timedelta
    close_after: timedelta | None = None


class SourceDefaults:
    """Defaults so a new source only writes what it actually does."""

    needs_detail_fetch: bool = False

    def payload_facts(self, payload: dict[str, Any]) -> JobDetail:
        _ = payload
        return JobDetail()

    def augment_text(self, payload: dict[str, Any], text: str) -> str:
        _ = payload
        return text


class JobSource(Protocol):
    id: str
    kind: str
    full_board: bool
    spec: SourceSpec
    needs_detail_fetch: bool

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]: ...

    def payload_facts(self, payload: dict[str, Any]) -> JobDetail: ...

    def augment_text(self, payload: dict[str, Any], text: str) -> str: ...


class RunPartial(Exception):
    """The source responded, but this scope did not finish cleanly."""

    def __init__(self, source_id: str, message: str) -> None:
        super().__init__(f"{source_id}: {message}")
        self.source_id = source_id

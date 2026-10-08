"""Adapter types. Fetch I/O stays at the edge; mapping is pure."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, Field

from jobhunt.http import HttpClient


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


class SourceAdapter(Protocol):
    id: str
    kind: str
    full_board: bool

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]: ...

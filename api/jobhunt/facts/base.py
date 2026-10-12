"""Parser contract. Every parser takes text and returns a JobDetail."""

from datetime import date
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field

FieldName = Literal["pay", "job_type", "workplace", "locations", "posted"]
FIELDS: tuple[FieldName, ...] = ("pay", "job_type", "workplace", "locations", "posted")
JobTypeName = Literal["fulltime", "parttime", "contract", "internship", "temporary"]
WorkplaceName = Literal["onsite", "hybrid", "remote"]
TextFormat = Literal["text", "markdown", "html"]


class Pay(BaseModel):
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    currency: str | None = None
    interval: str | None = None


class Place(BaseModel):
    city: str | None = None
    region: str | None = None
    country: str | None = None


class PayFact(BaseModel):
    value: Pay
    confidence: float = Field(ge=0, le=1)
    evidence: str
    span: tuple[int, int] | None = None
    parser_id: str


class TextFact(BaseModel):
    value: str
    confidence: float = Field(ge=0, le=1)
    evidence: str
    span: tuple[int, int] | None = None
    parser_id: str


class LocationFact(BaseModel):
    value: list[Place]
    confidence: float = Field(ge=0, le=1)
    evidence: str
    span: tuple[int, int] | None = None
    parser_id: str


class DateFact(BaseModel):
    value: date
    confidence: float = Field(ge=0, le=1)
    evidence: str
    span: tuple[int, int] | None = None
    parser_id: str


class JobDetail(BaseModel):
    """The five parsed Job details fields. Sources come from postings, not text."""

    pay: PayFact | None = None
    job_type: TextFact | None = None
    workplace: TextFact | None = None
    locations: LocationFact | None = None
    posted: DateFact | None = None

    def missing(self, wanted: set[FieldName]) -> set[FieldName]:
        gaps: set[FieldName] = set()
        for field in wanted:
            if _get(self, field) is None:
                gaps.add(field)
        return gaps


class ParseHints(BaseModel):
    format: TextFormat = "text"
    country: str | None = None
    source_id: str | None = None
    wanted: set[FieldName] = Field(default_factory=lambda: set(FIELDS))


class JobDetailParser(Protocol):
    parser_id: str
    sends_data_offsite: bool

    def parse(self, text: str, hints: ParseHints | None = None) -> JobDetail: ...


def _get(
    detail: JobDetail, field: FieldName
) -> PayFact | TextFact | LocationFact | DateFact | None:
    if field == "pay":
        return detail.pay
    if field == "job_type":
        return detail.job_type
    if field == "workplace":
        return detail.workplace
    if field == "locations":
        return detail.locations
    return detail.posted


def wants(hints: ParseHints | None, field: FieldName) -> bool:
    if hints is None:
        return True
    return field in hints.wanted


def prefer(primary: JobDetail, fallback: JobDetail) -> JobDetail:
    """Keep a field from primary when it has one, otherwise take fallback."""
    return JobDetail(
        pay=primary.pay or fallback.pay,
        job_type=primary.job_type or fallback.job_type,
        workplace=primary.workplace or fallback.workplace,
        locations=primary.locations or fallback.locations,
        posted=primary.posted or fallback.posted,
    )

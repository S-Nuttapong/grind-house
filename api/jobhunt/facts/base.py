"""Parser contract. Every parser takes a PostingInput and returns a JobDetail."""

from datetime import date
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field

FieldName = Literal[
    "pay", "job_type", "workplace", "locations", "posted", "role", "level", "experience"
]
FIELDS: tuple[FieldName, ...] = (
    "pay",
    "job_type",
    "workplace",
    "locations",
    "posted",
    "role",
    "level",
    "experience",
)
LEVELS: tuple[str, ...] = (
    "intern",
    "junior",
    "mid",
    "senior",
    "staff",
    "principal",
    "lead",
    "manager",
)
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


class Experience(BaseModel):
    """Whole years the posting asks for. A missing side is an open end."""

    minimum: int | None = None
    maximum: int | None = None


class ExperienceFact(BaseModel):
    value: Experience
    confidence: float = Field(ge=0, le=1)
    evidence: str
    span: tuple[int, int] | None = None
    parser_id: str


class JobDetail(BaseModel):
    """Parsed job fields. A missing field is None, including level (stored as unknown)."""

    pay: PayFact | None = None
    job_type: TextFact | None = None
    workplace: TextFact | None = None
    locations: LocationFact | None = None
    posted: DateFact | None = None
    role: TextFact | None = None
    level: TextFact | None = None
    experience: ExperienceFact | None = None

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


class PostingInput(BaseModel):
    """Everything a parser may see. It does not look up the source itself."""

    source_id: str | None = None
    title: str = ""
    location_raw: str | None = None
    remote_hint: str | None = None
    employment_type_raw: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_interval: str | None = None
    posted_at: date | None = None
    description_md: str = ""
    source_facts: JobDetail = Field(default_factory=JobDetail)
    role_hint: str | None = None
    level_hint: str | None = None


class DetailParser(Protocol):
    parser_id: str
    sends_data_offsite: bool

    def parse(self, posting: PostingInput, hints: ParseHints | None = None) -> JobDetail: ...


def as_input(posting: PostingInput | str) -> PostingInput:
    if isinstance(posting, str):
        return PostingInput(description_md=posting)
    return posting


def _get(
    detail: JobDetail, field: FieldName
) -> PayFact | TextFact | LocationFact | DateFact | ExperienceFact | None:
    if field == "pay":
        return detail.pay
    if field == "job_type":
        return detail.job_type
    if field == "workplace":
        return detail.workplace
    if field == "locations":
        return detail.locations
    if field == "posted":
        return detail.posted
    if field == "role":
        return detail.role
    if field == "level":
        return detail.level
    return detail.experience


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
        role=primary.role or fallback.role,
        level=primary.level or fallback.level,
        experience=primary.experience or fallback.experience,
    )

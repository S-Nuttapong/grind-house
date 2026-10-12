"""Claude detail parser. The schema and the prompt live in this file."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from jobhunt.core.claude import CallMeta, ClaudeError, structured_call
from jobhunt.facts.base import (
    LEVELS,
    DateFact,
    JobDetail,
    LocationFact,
    ParseHints,
    Pay,
    PayFact,
    Place,
    PostingInput,
    TextFact,
    as_input,
    prefer,
)
from jobhunt.scrape.normalize.role import role_ids

_MODEL = "claude-haiku-5-5"
_PROMPT_VERSION = "v1"
_MAX_TOKENS = 1024
_DESCRIPTION_CAP = 20_000

_ROLES = tuple(sorted(role_ids())) + ("unknown",)
_LEVELS = LEVELS + ("unknown",)
_WORKPLACES = ("onsite", "hybrid", "remote", "unknown")
_JOB_TYPES = ("fulltime", "parttime", "contract", "internship", "temporary", "unknown")
_INTERVALS = ("yearly", "monthly", "weekly", "daily", "hourly", "unknown")

_SYSTEM = """Extract facts from one job posting. Use only what the posting says.

role is a slug from the schema, or unknown.
level is intern, junior, mid, senior, staff, principal, lead, or manager.
Take level from the title or from explicit seniority wording.
Do not infer level from years of experience alone. When in doubt, unknown.
workplace, job_type, currency, interval, country, and posted are unknown when absent.
minimum and maximum are decimal strings, or empty when absent.
city is empty when absent.
Each evidence field is a verbatim substring of the title or description, or empty.
Do not guess.
"""


class ParsedFields(BaseModel):
    """Every property is required. Unknown is a value, not a missing key."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[*_ROLES]  # type: ignore[valid-type]
    level: Literal[*_LEVELS]  # type: ignore[valid-type]
    workplace: Literal[*_WORKPLACES]  # type: ignore[valid-type]
    job_type: Literal[*_JOB_TYPES]  # type: ignore[valid-type]
    country: str
    city: str
    currency: str
    interval: Literal[*_INTERVALS]  # type: ignore[valid-type]
    minimum: str
    maximum: str
    posted: str
    evidence_role: str
    evidence_level: str
    evidence_workplace: str
    evidence_job_type: str
    evidence_location: str
    evidence_pay: str
    evidence_posted: str


class ClaudeParser:
    """Sends the posting to Claude. Board facts already on the input are kept."""

    sends_data_offsite = True

    def __init__(self, model: str = _MODEL) -> None:
        self.model = model
        self.parser_id = f"{model}/{_PROMPT_VERSION}"
        self.calls: list[CallMeta] = []

    def parse(self, posting: PostingInput | str, hints: ParseHints | None = None) -> JobDetail:
        del hints
        item = as_input(posting)
        try:
            parsed, meta = structured_call(
                model=self.model,
                system=_SYSTEM,
                user=_user(item),
                output=ParsedFields,
                max_tokens=_MAX_TOKENS,
            )
            self.calls.append(meta)
        except ClaudeError:
            raise
        return prefer(item.source_facts, detail_from_parsed(parsed, self.parser_id))


def detail_from_parsed(parsed: ParsedFields, parser_id: str) -> JobDetail:
    return JobDetail(
        role=_text(parsed.role, parsed.evidence_role, parser_id),
        level=_text(parsed.level, parsed.evidence_level, parser_id),
        workplace=_text(parsed.workplace, parsed.evidence_workplace, parser_id),
        job_type=_text(parsed.job_type, parsed.evidence_job_type, parser_id),
        locations=_location(parsed, parser_id),
        pay=_pay(parsed, parser_id),
        posted=_posted(parsed, parser_id),
    )


def _user(item: PostingInput) -> str:
    description = item.description_md[:_DESCRIPTION_CAP]
    return "\n".join(
        (
            f"Title: {item.title}",
            f"Location: {item.location_raw or ''}",
            f"Employment: {item.employment_type_raw or ''}",
            "Description:",
            description,
        )
    )


def _text(value: str, evidence: str, parser_id: str) -> TextFact | None:
    if value == "unknown" or value == "":
        return None
    return TextFact(value=value, confidence=1.0, evidence=evidence, parser_id=parser_id)


def _location(parsed: ParsedFields, parser_id: str) -> LocationFact | None:
    if parsed.country == "unknown" or parsed.country == "":
        return None
    city = parsed.city.strip() or None
    return LocationFact(
        value=[Place(city=city, country=parsed.country.upper())],
        confidence=1.0,
        evidence=parsed.evidence_location,
        parser_id=parser_id,
    )


def _pay(parsed: ParsedFields, parser_id: str) -> PayFact | None:
    minimum = _decimal(parsed.minimum)
    maximum = _decimal(parsed.maximum)
    if minimum is None and maximum is None:
        return None
    currency = None if parsed.currency in {"", "unknown"} else parsed.currency.upper()
    interval = None if parsed.interval == "unknown" else parsed.interval
    return PayFact(
        value=Pay(minimum=minimum, maximum=maximum, currency=currency, interval=interval),
        confidence=1.0,
        evidence=parsed.evidence_pay,
        parser_id=parser_id,
    )


def _posted(parsed: ParsedFields, parser_id: str) -> DateFact | None:
    if parsed.posted in {"", "unknown"}:
        return None
    try:
        value = date.fromisoformat(parsed.posted)
    except ValueError:
        return None
    return DateFact(
        value=value, confidence=1.0, evidence=parsed.evidence_posted, parser_id=parser_id
    )


def _decimal(text: str) -> Decimal | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return Decimal(stripped)
    except InvalidOperation:
        return None

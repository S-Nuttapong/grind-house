"""What to extract from a posting. No provider, no SDK."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from jobhunt.facts.base import (
    LEVELS,
    DateFact,
    JobDetail,
    LocationFact,
    Pay,
    PayFact,
    Place,
    PostingInput,
    TextFact,
)
from jobhunt.scrape.normalize.role import role_ids

_PROMPT_PATH = Path(__file__).parent / "prompts" / "job_facts.md"
_DESCRIPTION_CAP = 20_000
_MAX_TOKENS = 1024

_ROLES = tuple(sorted(role_ids())) + ("unknown",)
_LEVELS = LEVELS + ("unknown",)
_WORKPLACES = ("onsite", "hybrid", "remote", "unknown")
_JOB_TYPES = ("fulltime", "parttime", "contract", "internship", "temporary", "unknown")
_INTERVALS = ("yearly", "monthly", "weekly", "daily", "hourly", "unknown")


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


@dataclass(frozen=True)
class ExtractionSpec:
    version: str
    system: str
    render_user: Callable[[PostingInput], str]
    output: type[ParsedFields]
    max_tokens: int


def render_user(item: PostingInput) -> str:
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


def _load_prompt(path: Path) -> tuple[str, str]:
    raw = path.read_text()
    if not raw.startswith("---\n"):
        raise ValueError(f"{path.name} needs a version front matter")
    _marker, header, body = raw.split("---\n", 2)
    version = ""
    for line in header.splitlines():
        if line.startswith("version:"):
            version = line.split(":", 1)[1].strip()
    if not version:
        raise ValueError(f"{path.name} has no version")
    return version, body.lstrip("\n")


_VERSION, _SYSTEM = _load_prompt(_PROMPT_PATH)

JOB_FACTS = ExtractionSpec(
    version=_VERSION,
    system=_SYSTEM,
    render_user=render_user,
    output=ParsedFields,
    max_tokens=_MAX_TOKENS,
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
    minimum, maximum = _close_single_amount(minimum, maximum, parsed.evidence_pay)
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


def _close_single_amount(
    minimum: Decimal | None, maximum: Decimal | None, evidence: str
) -> tuple[Decimal | None, Decimal | None]:
    """A bare amount is a point. Only "up to" or "from" leaves one side open."""
    folded = evidence.casefold()
    ceiling = any(phrase in folded for phrase in ("up to", "up-to", "at most", "maximum of"))
    floor = folded.rstrip().endswith("+") or any(
        phrase in folded for phrase in ("from ", "at least", "minimum of")
    )
    if minimum is not None and maximum is None and not floor:
        return minimum, minimum
    if maximum is not None and minimum is None and not ceiling:
        return maximum, maximum
    return minimum, maximum


def _decimal(text: str) -> Decimal | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return Decimal(stripped)
    except InvalidOperation:
        return None

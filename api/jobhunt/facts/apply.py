"""Build the JobDetail for one posting and store it."""

from typing import Any

from psycopg import Connection

from jobhunt.facts.api_fields import augment_text, from_payload
from jobhunt.facts.base import FIELDS, FieldName, JobDetail, ParseHints, prefer
from jobhunt.facts.config import chains
from jobhunt.facts.default import DefaultParser
from jobhunt.facts.merge import merge_facts, save_facts
from jobhunt.scrape.sources.base import RawPosting

_default = DefaultParser()
_WORK = {"onsite", "hybrid", "remote"}
_TYPES = {"fulltime", "parttime", "contract", "internship", "temporary"}


def build_detail(posting: RawPosting, description: str | None) -> tuple[JobDetail, str]:
    """Api fields win. The description parser runs only for fields whose chain names it."""
    payload = posting.payload if isinstance(posting.payload, dict) else {}
    api = from_payload(posting.source_id, payload)
    text_fields = {field for field in FIELDS if "default" in chains()[field]}
    if not text_fields:
        return api, "done"
    country = _country(api)
    text = augment_text(posting.source_id, payload, description or "")
    parsed = _default.parse(
        text,
        ParseHints(
            format="markdown",
            country=country,
            source_id=posting.source_id,
            wanted=text_fields,
        ),
    )
    combined = prefer(api, parsed)
    return combined, "pending" if needs_gliner(combined) else "done"


def needs_gliner(detail: JobDetail) -> bool:
    order = chains()
    for field in FIELDS:
        if "gliner" in order[field] and _empty(detail, field):
            return True
    return False


def record(
    conn: Connection[Any], job_id: int, posting_id: int, detail: JobDetail, status: str
) -> None:
    save_facts(conn, posting_id, detail, status)
    merge_facts(conn, job_id)


def _country(detail: JobDetail) -> str | None:
    if detail.locations is None or not detail.locations.value:
        return None
    return detail.locations.value[0].country


def _empty(detail: JobDetail, field: FieldName) -> bool:
    if field == "pay":
        return detail.pay is None
    if field == "job_type":
        return detail.job_type is None or detail.job_type.value not in _TYPES
    if field == "workplace":
        return detail.workplace is None or detail.workplace.value not in _WORK
    if field == "locations":
        return detail.locations is None or not detail.locations.value
    return detail.posted is None

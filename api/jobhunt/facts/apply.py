"""Build the JobDetail for one posting and store it."""

from typing import Any

from psycopg import Connection

from jobhunt.composition import COMPOSITION, require_on_machine
from jobhunt.core.log import get_logger
from jobhunt.facts.api_fields import augment_text, from_payload
from jobhunt.facts.base import JobDetail, PostingInput
from jobhunt.facts.contract import check_facts
from jobhunt.facts.merge import merge_facts, save_facts
from jobhunt.scrape.sources.base import RawPosting

log = get_logger("facts")


def posting_input(posting: RawPosting, description: str | None) -> PostingInput:
    payload = posting.payload if isinstance(posting.payload, dict) else {}
    return PostingInput(
        source_id=posting.source_id,
        title=posting.title,
        location_raw=posting.location_raw,
        remote_hint=posting.remote_hint,
        employment_type_raw=posting.employment_type_raw,
        salary_min=posting.salary_min,
        salary_max=posting.salary_max,
        salary_currency=posting.salary_currency,
        salary_interval=posting.salary_interval_raw,
        posted_at=posting.posted_at,
        description_md=augment_text(posting.source_id, payload, description or ""),
        source_facts=from_payload(posting.source_id, payload),
        role_hint=posting.role_hint,
        level_hint=posting.level_hint,
    )


def build_detail(posting: RawPosting, description: str | None) -> tuple[JobDetail, str]:
    """Run the composed parser, then the contract. A parser error is stored as failed."""
    require_on_machine(COMPOSITION.parser, "parser")
    item = posting_input(posting, description)
    try:
        detail = COMPOSITION.parser.parse(item)
    except Exception as exc:
        log.warning("parser failed: %s", type(exc).__name__)
        return JobDetail(), "failed"
    return check_facts(detail, title=item.title, description=item.description_md), "done"


def record(
    conn: Connection[Any], job_id: int, posting_id: int, detail: JobDetail, status: str
) -> None:
    save_facts(conn, posting_id, detail, status)
    merge_facts(conn, job_id)

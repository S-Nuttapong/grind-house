"""Look up the source that owns a payload and ask it for facts."""

from typing import Any

from jobhunt.facts.base import JobDetail
from jobhunt.facts.mapping import map_job_type, map_workplace

__all__ = ["augment_text", "from_payload", "map_job_type", "map_workplace"]


def from_payload(source_id: str, payload: dict[str, Any]) -> JobDetail:
    """Map one source payload into a JobDetail. Unknown sources stay empty."""
    from jobhunt.composition import COMPOSITION

    try:
        source = COMPOSITION.source(source_id)
    except ValueError:
        return JobDetail()
    return source.payload_facts(payload)


def augment_text(source_id: str, payload: dict[str, Any], description: str) -> str:
    """Let the source append structured lines the description does not carry."""
    from jobhunt.composition import COMPOSITION

    try:
        source = COMPOSITION.source(source_id)
    except ValueError:
        return description
    return source.augment_text(payload, description)

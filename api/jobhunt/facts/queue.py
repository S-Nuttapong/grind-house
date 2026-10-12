"""Drain postings that still need the GLiNER pass. Runs in the fit worker."""

from jobhunt.core.db import tx
from jobhunt.core.log import get_logger
from jobhunt.facts.api_fields import augment_text
from jobhunt.facts.apply import _country
from jobhunt.facts.base import FIELDS, JobDetail, ParseHints, prefer
from jobhunt.facts.config import gliner_enabled
from jobhunt.facts.merge import merge_facts, save_facts
from jobhunt.facts.registry import create

log = get_logger("facts")


def drain_once(limit: int = 20) -> int:
    """Parse up to `limit` pending postings. Returns how many were finished."""
    if not gliner_enabled():
        return 0
    with tx() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.job_id, j.description_md, p.source_id, rp.payload, p.facts
            FROM postings p
            JOIN jobs j ON j.id = p.job_id
            LEFT JOIN LATERAL (
                SELECT payload FROM raw_payloads r
                WHERE r.posting_id = p.id
                ORDER BY fetched_at DESC
                LIMIT 1
            ) rp ON true
            WHERE p.facts_status = 'pending' AND j.closed_at IS NULL
            ORDER BY p.id
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    if not rows:
        return 0
    parser = create("gliner")
    done = 0
    for row in rows:
        if not isinstance(row[0], int) or not isinstance(row[1], int):
            continue
        posting_id = row[0]
        job_id = row[1]
        description = row[2] if isinstance(row[2], str) else ""
        source_id = str(row[3])
        payload = row[4] if isinstance(row[4], dict) else {}
        existing = JobDetail.model_validate(row[5]) if isinstance(row[5], dict) else JobDetail()
        text = augment_text(source_id, payload, description)
        parsed = parser.parse(
            text,
            ParseHints(
                format="markdown",
                country=_country(existing),
                source_id=source_id,
                wanted=existing.missing(set(FIELDS)),
            ),
        )
        combined = prefer(existing, parsed)
        with tx() as conn:
            save_facts(conn, posting_id, combined, "done")
            merge_facts(conn, job_id)
        done += 1
    log.info("facts drain finished %s", done)
    return done

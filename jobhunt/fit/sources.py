"""Build the profile text a fit run scores against, and record its hash."""

import hashlib
from typing import Any

from psycopg import Connection

from jobhunt.db import brag_repo, fit_repo
from jobhunt.fit.base import JobFitModel

_NO_RESUME = "Select a resume on the Profile page before scoring against one."


class SourceError(Exception):
    """The requested source has nothing to score against."""


def bank_text(conn: Connection[Any]) -> str:
    parts = [fit_repo.get_bank_profile(conn)]
    for doc in brag_repo.list_brag_docs(conn):
        parts.append(_doc_text(doc))
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def resume_text(conn: Connection[Any]) -> tuple[str, int]:
    selected = fit_repo.selected_resume(conn)
    if selected is None:
        raise SourceError(_NO_RESUME)
    return str(selected["text"]), int(selected["id"])


def resolve(conn: Connection[Any], mode: str, model: JobFitModel) -> tuple[str, str, int | None]:
    """Return (source_hash, profile_text, resume_id) and record the source."""
    if mode == "bank":
        # Every brag doc is included. The model no longer drops any of them.
        _ = model.model_id
        text = bank_text(conn)
        resume_id = None
    elif mode == "resume":
        text, resume_id = resume_text(conn)
    else:
        raise SourceError(f"unknown fit mode {mode!r}")
    if not text.strip():
        raise SourceError(f"the {mode} profile is empty")
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    fit_repo.upsert_fit_source(conn, source_hash=source_hash, kind=mode, resume_id=resume_id)
    return source_hash, text, resume_id


def job_hash(title: str, description: str | None) -> str:
    payload = f"{title}\n{description or ''}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _doc_text(doc: dict[str, Any]) -> str:
    role = str(doc["role"] or "")
    company = str(doc["company"] or "")
    if role and company:
        where = f"{role} at {company}"
    else:
        where = role or company
    metric_lines = [f"{item['name']}: {item['value']}" for item in doc["metrics"] or []]
    tags = " ".join(str(tag["name"]) for tag in doc["tags"] or [])
    lines = [
        str(doc["title"]),
        where,
        "\n".join(metric_lines),
        str(doc["description_md"] or ""),
        tags,
    ]
    return "\n".join(line for line in lines if line)

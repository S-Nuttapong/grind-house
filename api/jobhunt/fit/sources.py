"""Build the brag docs a fit run scores against, and record their hash."""

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from psycopg import Connection

from jobhunt.brag import repo as brag_repo
from jobhunt.fit import repo as fit_repo
from jobhunt.fit.base import BragDoc, FitScorer
from jobhunt.profile import repo as profile_repo

_NO_RESUME = "Select a resume on the Profile page before scoring against one."
_SECTION = re.compile(r"(?=^#{1,6}[ \t]+)", re.MULTILINE)


class SourceError(Exception):
    """The requested source has nothing to score against."""


def bank_docs(conn: Connection[Any]) -> list[BragDoc]:
    docs: list[BragDoc] = []
    summary = profile_repo.get_bank_profile(conn).strip()
    if summary:
        docs.append(BragDoc(id="profile", text=summary))
    for doc in brag_repo.list_brag_docs(conn):
        text = _doc_text(doc).strip()
        if text:
            docs.append(BragDoc(id=str(doc["id"]), text=text))
    return docs


def bank_text(conn: Connection[Any]) -> str:
    return joined_text(bank_docs(conn))


def resume_text(conn: Connection[Any]) -> tuple[str, int]:
    selected = profile_repo.selected_resume(conn)
    if selected is None:
        raise SourceError(_NO_RESUME)
    return str(selected["text"]), int(selected["id"])


def resume_sections(resume_id: int, text: str) -> list[BragDoc]:
    """One document per Markdown heading. The whole resume is one document when it has none."""
    parts = [part.strip() for part in _SECTION.split(text) if part.strip()]
    return [
        BragDoc(id=f"resume:{resume_id}#{index}", text=part)
        for index, part in enumerate(parts, start=1)
    ]


def current_docs(conn: Connection[Any], mode: str) -> list[BragDoc]:
    if mode == "bank":
        docs = bank_docs(conn)
    elif mode == "resume":
        text, resume_id = resume_text(conn)
        docs = resume_sections(resume_id, text)
    else:
        raise SourceError(f"unknown fit mode {mode!r}")
    if not any(doc.text.strip() for doc in docs):
        raise SourceError(f"the {mode} profile is empty")
    return docs


def resolve(
    conn: Connection[Any], mode: str, model: FitScorer
) -> tuple[str, list[BragDoc], int | None]:
    """Return (source_hash, docs, resume_id) and record the source."""
    _ = model.model_id
    docs = current_docs(conn, mode)
    resume_id = _resume_id(docs) if mode == "resume" else None
    source_hash = docs_hash(docs)
    fit_repo.upsert_fit_source(conn, source_hash=source_hash, kind=mode, resume_id=resume_id)
    return source_hash, docs, resume_id


def docs_hash(docs: Sequence[BragDoc]) -> str:
    payload = "\n\n".join(f"{doc.id}\n{doc.text}" for doc in docs)
    return hashlib.sha256(payload.encode()).hexdigest()


def joined_text(docs: Sequence[BragDoc]) -> str:
    return "\n\n".join(doc.text.strip() for doc in docs if doc.text.strip())


def job_hash(title: str, description: str | None) -> str:
    payload = f"{title}\n{description or ''}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _resume_id(docs: Sequence[BragDoc]) -> int | None:
    for doc in docs:
        prefix, _, _rest = doc.id.partition("#")
        if prefix.startswith("resume:"):
            return int(prefix.removeprefix("resume:"))
    return None


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

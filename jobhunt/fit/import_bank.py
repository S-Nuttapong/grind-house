"""Read the brag-doc vault into the database. The vault is only ever read."""

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from psycopg import Connection

from jobhunt.db import brag_repo, fit_repo

_CONTACT_KEYS = {"name", "email", "phone", "links", "location", "work_authorization"}


def import_bank(conn: Connection[Any], bank_dir: Path) -> dict[str, int]:
    """Upsert brag docs, the profile body, and resume.json files. Returns counts."""
    split = _frontmatter_parser(bank_dir)
    entries = 0
    for path in sorted((bank_dir / "Entries").glob("BB-*.md")):
        frontmatter, body = split(path.read_text())
        doc = _doc(frontmatter, body)
        if doc is None:
            continue
        _save(conn, doc)
        entries += 1

    profile_path = bank_dir / "_Profile.md"
    if profile_path.exists():
        frontmatter, body = split(profile_path.read_text())
        fit_repo.set_bank_profile(conn, body.strip())
        del frontmatter  # contact details in the frontmatter are never stored

    resumes = 0
    resumes_dir = bank_dir / "Resumes"
    if resumes_dir.is_dir():
        for resume_json in sorted(resumes_dir.glob("*/resume.json")):
            fit_repo.insert_resume(
                conn,
                name=resume_json.parent.name,
                text=_resume_text(json.loads(resume_json.read_text())),
                filename="resume.json",
                origin="vault",
            )
            resumes += 1
    return {"entries": entries, "resumes": resumes}


def _save(conn: Connection[Any], doc: dict[str, Any]) -> None:
    tag_ids = [brag_repo.get_or_create_tag(conn, name)[0]["id"] for name in doc["tags"]]
    metrics = []
    for item in doc["metrics"]:
        key = brag_repo.get_or_create_metric_key(conn, item["key"])[0]
        metrics.append({"metric_key_id": key["id"], "value": item["value"]})
    brag_repo.save_brag_doc(
        conn,
        {
            "id": doc["id"],
            "title": doc["title"],
            "date": doc["date"],
            "company": doc["company"],
            "role": doc["role"],
            "description_md": doc["description_md"],
            "origin": "vault",
            "tag_ids": tag_ids,
            "metrics": metrics,
            "attachments": doc["attachments"],
        },
    )


def _doc(frontmatter: dict[str, Any], body: str) -> dict[str, Any] | None:
    if not frontmatter.get("id") or frontmatter.get("date") is None:
        return None
    parsed = _as_date(frontmatter["date"])
    if parsed is None:
        return None
    tags = frontmatter.get("tags") or []
    return {
        "id": str(frontmatter["id"]),
        "title": str(frontmatter.get("title") or ""),
        "date": parsed,
        "company": _text_or_none(frontmatter.get("company")),
        "role": _text_or_none(frontmatter.get("role")),
        "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
        "metrics": _metrics(frontmatter.get("metrics")),
        "attachments": _attachments(frontmatter.get("attachments")),
        "description_md": body.strip(),
    }


def _metrics(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    metrics: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        if key and value:
            metrics.append({"key": key, "value": value})
    return metrics


def _attachments(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    attachments: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or "").strip()
        if link.startswith(("http://", "https://")):
            attachments.append({"type": "url", "link": link})
    return attachments


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resume_text(resume: dict[str, Any]) -> str:
    """Flatten a resume.json into text. Contact fields are left out."""
    parts: list[str] = []
    for key, value in resume.items():
        if key in _CONTACT_KEYS or key.startswith("contact"):
            continue
        parts.append(_flatten(value))
    return "\n".join(part for part in parts if part).strip()


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return "\n".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten(item) for item in value)
    return ""


def _frontmatter_parser(bank_dir: Path) -> Any:
    """Use the vault's own parser when the kit ships one."""
    kit = bank_dir / "_kit"
    if (kit / "bankutil.py").exists():
        sys.path.insert(0, str(kit))
        from bankutil import split_frontmatter  # type: ignore[import-not-found]

        def parse(text: str) -> tuple[dict[str, Any], str]:
            frontmatter, body = split_frontmatter(text)
            return dict(frontmatter), str(body)

        return parse

    import yaml

    marker = "---\n"

    def parse_local(text: str) -> tuple[dict[str, Any], str]:
        if not text.startswith(marker):
            return {}, text
        end = text.find("\n" + marker, len(marker))
        if end == -1:
            return {}, text
        raw = text[len(marker) : end]
        loaded = yaml.safe_load(raw) or {}
        body = text[end + len(marker) + 1 :]
        return (loaded if isinstance(loaded, dict) else {}), body

    return parse_local

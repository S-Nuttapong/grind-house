"""Read the brag-bank vault into the database. The vault is only ever read."""

import json
import sys
from pathlib import Path
from typing import Any

from psycopg import Connection

from jobhunt.db import fit_repo

_ROLES = {"led", "built", "co-built", "contributed"}
_STATUSES = {"draft", "needs-metric", "verified"}
_CONTACT_KEYS = {"name", "email", "phone", "links", "location", "work_authorization"}


def import_bank(conn: Connection[Any], bank_dir: Path) -> dict[str, int]:
    """Upsert entries, the profile body, and resume.json files. Returns counts."""
    split = _frontmatter_parser(bank_dir)
    entries = 0
    for path in sorted((bank_dir / "Entries").glob("BB-*.md")):
        frontmatter, body = split(path.read_text())
        if not frontmatter.get("id"):
            continue
        fit_repo.upsert_bank_entry(conn, _entry(frontmatter, body))
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


def _entry(frontmatter: dict[str, Any], body: str) -> dict[str, Any]:
    my_role = str(frontmatter.get("my_role") or "")
    status = str(frontmatter.get("status") or "draft")
    metrics = frontmatter.get("metrics") or []
    tags = frontmatter.get("tags") or []
    return {
        "id": str(frontmatter["id"]),
        "title": str(frontmatter.get("title") or ""),
        "company": frontmatter.get("company"),
        "role": frontmatter.get("role"),
        "period": str(frontmatter.get("period") or "") or None,
        "my_role": my_role if my_role in _ROLES else None,
        "scope": frontmatter.get("scope"),
        "metrics": metrics if isinstance(metrics, list) else [],
        "strength": frontmatter.get("strength"),
        "confidential": bool(frontmatter.get("confidential")),
        "status": status if status in _STATUSES else "draft",
        "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
        "body_md": body.strip(),
        "origin": "vault",
    }


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

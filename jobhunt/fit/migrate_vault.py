"""Rewrite old brag-bank frontmatter into brag docs. The body is not touched."""

import re
import shutil
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

_LEGACY_KEYS = {"period", "my_role", "scope", "strength", "confidential", "status"}
_MARKER = "---\n"


@dataclass(frozen=True)
class FileChange:
    path: Path
    action: str
    detail: str


def humanize_kind(kind: str | None) -> str:
    """Turn `page-experience` into `Page Experience`. A blank kind is General."""
    raw = (kind or "").replace("_", " ").replace("-", " ")
    words = [word for word in raw.split() if word]
    if not words:
        return "General"
    return " ".join(word[:1].upper() + word[1:].lower() for word in words)


def migrate_vault(
    bank_dir: Path, *, write: bool, backup_root: Path | None = None
) -> list[FileChange]:
    """Rewrite `Entries/BB-*.md`. Without `write`, only report what would change."""
    entries = bank_dir / "Entries"
    if not entries.is_dir():
        return []
    planned: list[tuple[Path, str, str]] = []
    changes: list[FileChange] = []
    for path in sorted(entries.glob("BB-*.md")):
        original = path.read_text()
        frontmatter, body = _split(original)
        if _already_migrated(frontmatter):
            changes.append(FileChange(path, "skip", "already a brag doc"))
            continue
        rewritten, detail = _rewrite(frontmatter, body, path)
        planned.append((path, rewritten, detail))
        changes.append(FileChange(path, "rewrite", detail))
    if write and planned:
        _backup(entries, backup_root or Path.home() / ".jobhunt" / "vault-backups")
        for path, rewritten, _detail in planned:
            path.write_text(rewritten)
    return changes


def _rewrite(frontmatter: dict[str, Any], body: str, path: Path) -> tuple[str, str]:
    fallback = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date()
    written = date_from_period(_text(frontmatter.get("period")), fallback)
    doc: dict[str, Any] = {
        "id": str(frontmatter.get("id") or path.stem.split(" ")[0]),
        "title": str(frontmatter.get("title") or ""),
        "date": written.isoformat(),
        "company": _text(frontmatter.get("company")),
        "role": _text(frontmatter.get("role")),
        "tags": _tags(frontmatter.get("tags")),
        "metrics": _metrics(frontmatter.get("metrics")),
        "attachments": _attachments(frontmatter.get("attachments")),
    }
    doc = {key: value for key, value in doc.items() if value is not None}
    dumped = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    detail = f"date {written.isoformat()}, {len(doc['metrics'])} metrics"
    return f"---\n{dumped}---\n{body}", detail


def date_from_period(period: str | None, fallback: date) -> date:
    """Last day of the month or year the period ends in.

    ``2025-08 – 2025-09`` is 2025-09-30. A year with no month, such as
    ``2021 – 2023``, is 31 December of that year. ``present`` is today.
    Anything else is `fallback`.
    """
    if not period:
        return fallback
    text = period.replace("–", "-").replace("—", "-").strip().strip("'\"")
    end = text.split(" - ")[-1].strip() if " - " in text else text
    if end.lower() == "present":
        return date.today()
    month_match = re.fullmatch(r"(\d{4})-(\d{2})", end)
    if month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        if 1 <= month <= 12 and 1900 <= year <= 2200:
            return date(year, month, monthrange(year, month)[1])
        return fallback
    year_match = re.fullmatch(r"(\d{4})", end)
    if year_match:
        year = int(year_match.group(1))
        if 1900 <= year <= 2200:
            return date(year, 12, 31)
    return fallback


def _already_migrated(frontmatter: dict[str, Any]) -> bool:
    if "date" not in frontmatter or _LEGACY_KEYS & set(frontmatter):
        return False
    metrics = frontmatter.get("metrics") or []
    if not isinstance(metrics, list):
        return False
    for item in metrics:
        if not isinstance(item, dict):
            return False
        if "key" not in item or "value" not in item:
            return False
        if "text" in item or "kind" in item:
            return False
    return True


def _metrics(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    metrics: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "key" in item and "value" in item and "text" not in item and "kind" not in item:
            key = str(item["key"]).strip()
            value = str(item["value"]).strip()
        else:
            key = humanize_kind(str(item["kind"]) if item.get("kind") else None)
            value = str(item.get("text") or "").strip()
        if key and value:
            metrics.append({"key": key, "value": value})
    return metrics


def _tags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(tag) for tag in raw if str(tag).strip()]


def _attachments(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    kept: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or "").strip()
        if link.startswith(("http://", "https://")):
            kept.append({"type": "url", "link": link})
    return kept


def _split(text: str) -> tuple[dict[str, Any], str]:
    """Return frontmatter and the exact bytes after the closing fence."""
    if not text.startswith(_MARKER):
        return {}, text
    end = text.find("\n" + _MARKER, len(_MARKER))
    if end == -1:
        return {}, text
    raw = text[len(_MARKER) : end]
    loaded = yaml.safe_load(raw) or {}
    body = text[end + len("\n" + _MARKER) :]
    return (loaded if isinstance(loaded, dict) else {}), body


def _backup(entries: Path, backup_root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    destination = backup_root / stamp / "Entries"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(entries, destination)
    return destination


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

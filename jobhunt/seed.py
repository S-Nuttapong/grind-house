"""Load companies and fetch scopes from config YAML. Safe to run again."""

from pathlib import Path
from typing import Any

import yaml
from psycopg import Connection

from jobhunt.db import repo, tx
from jobhunt.normalize.company import norm_company


def apply_seed(conn: Connection[Any], config_dir: Path | None = None) -> tuple[int, int]:
    root = config_dir or _config_dir()
    companies = _load(root / "companies.seed.yaml")
    scopes = _load(root / "scopes.seed.yaml")
    inserted_companies = 0
    for item in companies:
        if _upsert_company(conn, item):
            inserted_companies += 1
    inserted_scopes = 0
    for item in scopes:
        name = str(item["name"])
        if repo.scope_exists(conn, name):
            continue
        repo.insert_scope(
            conn,
            name=name,
            source_id=str(item["source_id"]),
            params=dict(item.get("params") or {}),
            cron=str(item["cron"]),
            timezone=str(item.get("timezone") or "Asia/Bangkok"),
        )
        inserted_scopes += 1
    return inserted_companies, inserted_scopes


def seed(config_dir: Path | None = None) -> tuple[int, int]:
    with tx() as conn:
        return apply_seed(conn, config_dir)


def _upsert_company(conn: Connection[Any], item: dict[str, Any]) -> bool:
    name = str(item["name"])
    name_norm = norm_company(name)
    existing = repo.get_company_by_name_norm(conn, name_norm)
    tier = item.get("tier")
    careers_url = item.get("careers_url")
    ats = item.get("ats")
    ats_slug = item.get("ats_slug")
    if existing is None:
        repo.insert_company(
            conn,
            name=name,
            name_norm=name_norm,
            tier=str(tier) if tier else None,
            careers_url=str(careers_url) if careers_url else None,
            ats=str(ats) if ats else None,
            ats_slug=str(ats_slug) if ats_slug else None,
        )
        return True
    conn.execute(
        """
        UPDATE companies SET
          tier = COALESCE(tier, %s),
          careers_url = COALESCE(careers_url, %s),
          ats = COALESCE(ats, %s),
          ats_slug = COALESCE(ats_slug, %s)
        WHERE id = %s
        """,
        (
            str(tier) if tier else None,
            str(careers_url) if careers_url else None,
            str(ats) if ats else None,
            str(ats_slug) if ats_slug else None,
            int(existing[0]),
        ),
    )
    return False


def _load(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text()) if path.exists() else []
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} must be a list")
    return [item for item in raw if isinstance(item, dict)]


def _config_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config"
        if candidate.is_dir():
            return candidate
    return Path("config")

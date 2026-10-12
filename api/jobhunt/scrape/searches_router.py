"""Edit scheduled searches and the role allow-list."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from jobhunt.core.db import tx
from jobhunt.core.paths import config_path
from jobhunt.scrape import repo
from jobhunt.scrape.markets import load_markets
from jobhunt.scrape.normalize.role import role_ids
from jobhunt.scrape.tick import tick

router = APIRouter(prefix="/api")

_BOARDS = (
    "linkedin_guest",
    "seek",
    "indeed",
    "glassdoor",
    "adzuna",
    "reed",
    "jooble",
    "mycareersfuture",
    "naukri",
)


class SourceInput(BaseModel):
    source_id: str
    poll_minutes: int = Field(default=30, ge=1, le=10080)
    enabled: bool = True


class SearchInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    keywords: list[str] = Field(min_length=1, max_length=12)
    countries: list[str] = Field(min_length=1, max_length=32)
    timezone: str = "Asia/Bangkok"
    enabled: bool = True
    sources: list[SourceInput] = Field(min_length=1)


class SearchSource(BaseModel):
    source_id: str
    poll_minutes: int
    enabled: bool
    paused_until: datetime | None = None
    strikes: int = 0
    last_polled_at: datetime | None = None
    last_status: str | None = None


class Search(BaseModel):
    id: int
    name: str
    keywords: list[str]
    countries: list[str]
    timezone: str
    enabled: bool
    sources: list[SearchSource]


class SettingsBody(BaseModel):
    allowed_roles: list[str] = Field(min_length=1)


class Settings(BaseModel):
    allowed_roles: list[str]


class HookRow(BaseModel):
    id: int
    name: str
    phase: str
    exit_code: int | None
    duration_ms: int
    ran_at: datetime
    error: str | None


class HooksView(BaseModel):
    configured: list[dict[str, Any]]
    recent: list[HookRow]


@router.get("/searches", response_model=list[Search])
def list_searches() -> list[dict[str, Any]]:
    with tx() as conn:
        return repo.list_searches(conn)


@router.post("/searches", response_model=Search, status_code=201)
def create_search(body: SearchInput) -> dict[str, Any]:
    _reject(_problems(body))
    with tx() as conn:
        search_id = repo.insert_search(
            conn,
            name=body.name.strip(),
            keywords=_keywords(body),
            countries=_countries(body),
            timezone=body.timezone,
            enabled=body.enabled,
        )
        repo.replace_sources(conn, search_id, _source_rows(body))
        created = repo.get_search(conn, search_id)
    if created is None:
        raise HTTPException(status_code=500, detail="search was not stored")
    return created


@router.put("/searches/{search_id}", response_model=Search)
def update_search(search_id: int, body: SearchInput) -> dict[str, Any]:
    _reject(_problems(body))
    with tx() as conn:
        if repo.get_search(conn, search_id) is None:
            raise HTTPException(status_code=404, detail="no such search")
        repo.update_search(
            conn,
            search_id,
            name=body.name.strip(),
            keywords=_keywords(body),
            countries=_countries(body),
            timezone=body.timezone,
            enabled=body.enabled,
        )
        repo.replace_sources(conn, search_id, _source_rows(body))
        updated = repo.get_search(conn, search_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="no such search")
    return updated


@router.delete("/searches/{search_id}", status_code=204)
def delete_search(search_id: int) -> None:
    with tx() as conn:
        if not repo.delete_search(conn, search_id):
            raise HTTPException(status_code=404, detail="no such search")


@router.post("/searches/{search_id}/run", status_code=202)
def run_search(search_id: int, background: BackgroundTasks) -> dict[str, bool]:
    """Mark every market stale and poll this search under the tick lock."""
    with tx() as conn:
        if repo.get_search(conn, search_id) is None:
            raise HTTPException(status_code=404, detail="no such search")
        repo.mark_search_stale(conn, search_id)
    background.add_task(tick, search_id)
    return {"accepted": True}


@router.get("/scrape-settings", response_model=Settings)
def get_settings() -> Settings:
    with tx() as conn:
        return Settings(allowed_roles=repo.allowed_roles(conn))


@router.put("/scrape-settings", response_model=Settings)
def put_settings(body: SettingsBody) -> Settings:
    unknown = [role for role in body.allowed_roles if role not in role_ids()]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown roles: {', '.join(unknown)}")
    with tx() as conn:
        repo.save_allowed_roles(conn, body.allowed_roles)
        return Settings(allowed_roles=repo.allowed_roles(conn))


@router.get("/tick-hooks", response_model=HooksView)
def tick_hooks() -> HooksView:
    loaded = yaml.safe_load(config_path("scrape.yaml").read_text())
    tick_doc = loaded.get("tick") if isinstance(loaded, dict) else {}
    configured: list[dict[str, Any]] = []
    if isinstance(tick_doc, dict):
        for phase in ("before_start", "after"):
            hooks = tick_doc.get(phase) or []
            if isinstance(hooks, list):
                for hook in hooks:
                    if isinstance(hook, dict):
                        configured.append({"phase": phase, **hook})
    with tx() as conn:
        recent = [HookRow(**row) for row in repo.list_hooks(conn)]
    return HooksView(configured=configured, recent=recent)


def _problems(body: SearchInput) -> list[str]:
    problems: list[str] = []
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        problems.append(f"{body.timezone!r} is not a known timezone")
    markets = set(load_markets())
    for country in body.countries:
        if country.upper() not in markets:
            problems.append(f"{country} is not a configured market")
    seen: set[str] = set()
    with tx() as conn:
        floors = repo.source_min_seconds(conn)
    for source in body.sources:
        if source.source_id not in _BOARDS:
            problems.append(f"{source.source_id} is not a search board")
            continue
        if source.source_id in seen:
            problems.append(f"{source.source_id} is listed twice")
        seen.add(source.source_id)
        floor = floors.get(source.source_id, 0)
        if source.poll_minutes * 60 < floor:
            problems.append(f"{source.source_id} poll is shorter than its minimum interval")
    if not _keywords(body):
        problems.append("add at least one keyword")
    return problems


def _keywords(body: SearchInput) -> list[str]:
    return [word.strip() for word in body.keywords if word.strip()]


def _countries(body: SearchInput) -> list[str]:
    return [country.upper() for country in body.countries]


def _source_rows(body: SearchInput) -> list[tuple[str, int, bool]]:
    return [(source.source_id, source.poll_minutes, source.enabled) for source in body.sources]


def _reject(problems: list[str]) -> None:
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))

"""Scrape run history for the board's Runs page."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from jobhunt.core.db import tx
from jobhunt.scrape import repo

router = APIRouter(prefix="/api")


class Run(BaseModel):
    id: int
    source_id: str
    scope_name: str | None
    status: str
    fetched: int | None
    new_jobs: int | None
    updated: int | None
    closed: int | None
    skipped: int = 0
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    source_alert: bool = False


@router.get("/runs", response_model=list[Run])
def runs() -> list[Run]:
    with tx() as conn:
        alerts = repo.alert_sources(conn)
        return [
            Run(**row, source_alert=str(row["source_id"]) in alerts) for row in repo.list_runs(conn)
        ]

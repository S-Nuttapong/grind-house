"""One-off fill of empty job columns. Batches commit so a stop can resume."""

import time
from pathlib import Path
from typing import Any

from psycopg import Connection

from jobhunt.composition import COMPOSITION
from jobhunt.core.log import get_logger
from jobhunt.core.paths import API_ROOT
from jobhunt.facts.api_fields import augment_text, from_payload
from jobhunt.facts.base import JobDetail, PostingInput
from jobhunt.facts.contract import check_facts
from jobhunt.facts.coverage import coverage_table
from jobhunt.facts.merge import merge_facts, save_facts

log = get_logger("facts")

_BACKUP = "jobs_facts_backup_20261011"
_BATCH = 200
_COLUMNS = (
    "country",
    "city",
    "remote",
    "employment_type",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_interval",
    "salary_usd_year_min",
    "posted_at",
)


def run_backfill(conn: Connection[Any], *, dry_run: bool = False, restore: bool = False) -> str:
    if restore:
        _restore(conn)
        conn.commit()
        return "restored"
    _snapshot(conn)
    conn.commit()
    before = coverage_table(conn)
    if dry_run:
        _fill(conn, dry_run=True)
        after = coverage_table(conn)
        conn.rollback()
        return f"before\n{before}\n\nafter (rolled back)\n{after}"
    _fill(conn, dry_run=False)
    after = coverage_table(conn)
    return f"before\n{before}\n\nafter\n{after}"


def _snapshot(conn: Connection[Any]) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_BACKUP} AS
        SELECT id, {", ".join(_COLUMNS)} FROM jobs WHERE false
        """
    )
    exists = conn.execute(f"SELECT 1 FROM {_BACKUP} LIMIT 1").fetchone()
    if exists is not None:
        return
    conn.execute(
        f"""
        INSERT INTO {_BACKUP} (id, {", ".join(_COLUMNS)})
        SELECT id, {", ".join(_COLUMNS)} FROM jobs
        """
    )


def _restore(conn: Connection[Any]) -> None:
    assignments = ", ".join(f"{column} = b.{column}" for column in _COLUMNS)
    conn.execute(
        f"""
        UPDATE jobs j SET {assignments}
        FROM {_BACKUP} b WHERE j.id = b.id
        """
    )


def _fill(conn: Connection[Any], *, dry_run: bool) -> None:
    parser = COMPOSITION.parser
    last = 0 if dry_run else _read_checkpoint()
    total = conn.execute("SELECT count(*) FROM jobs WHERE closed_at IS NULL").fetchone()
    job_total = int(total[0]) if total else 0
    done = conn.execute(
        "SELECT count(*) FROM jobs WHERE closed_at IS NULL AND id <= %s", (last,)
    ).fetchone()
    finished = int(done[0]) if done else 0
    started = time.perf_counter()
    while True:
        jobs = conn.execute(
            """
            SELECT id, description_md FROM jobs
            WHERE closed_at IS NULL AND id > %s
            ORDER BY id
            LIMIT %s
            """,
            (last, _BATCH),
        ).fetchall()
        if not jobs:
            break
        for job_id, description in jobs:
            _one(conn, parser, int(job_id), description if isinstance(description, str) else "")
            last = int(job_id)
            finished += 1
        if dry_run:
            continue
        conn.commit()
        _write_checkpoint(last)
        elapsed = time.perf_counter() - started
        rate = (finished - (finished - len(jobs))) / elapsed if elapsed else 0
        remaining = max(job_total - finished, 0)
        eta = remaining / rate / 60 if rate else 0
        print(
            f"backfill {finished}/{job_total} jobs/min {rate * 60:.1f} eta {eta:.0f} min",
            flush=True,
        )
        started = time.perf_counter()


def _one(conn: Connection[Any], parser: Any, job_id: int, description: str) -> None:
    rows = conn.execute(
        """
        SELECT p.id, p.source_id, rp.payload
        FROM postings p
        LEFT JOIN LATERAL (
            SELECT payload FROM raw_payloads r
            WHERE r.posting_id = p.id
            ORDER BY fetched_at DESC
            LIMIT 1
        ) rp ON true
        WHERE p.job_id = %s
        """,
        (job_id,),
    ).fetchall()
    for posting_id, source_id, payload in rows:
        body = payload if isinstance(payload, dict) else {}
        item = PostingInput(
            source_id=str(source_id),
            description_md=augment_text(str(source_id), body, description),
            source_facts=from_payload(str(source_id), body),
        )
        try:
            parsed = check_facts(
                parser.parse(item), title=item.title, description=item.description_md
            )
            status = "done"
        except Exception as exc:
            log.warning("parser failed: %s", type(exc).__name__)
            parsed = JobDetail()
            status = "failed"
        save_facts(conn, int(posting_id), parsed, status)
    merge_facts(conn, job_id)


def _checkpoint_path() -> Path:
    directory = API_ROOT / "reports"
    directory.mkdir(exist_ok=True)
    return directory / "facts_backfill.checkpoint"


def _read_checkpoint() -> int:
    path = _checkpoint_path()
    if not path.exists():
        return 0
    text = path.read_text().strip()
    return int(text) if text else 0


def _write_checkpoint(job_id: int) -> None:
    _checkpoint_path().write_text(str(job_id))

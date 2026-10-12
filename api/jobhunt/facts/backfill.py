"""Fill empty role, location, level, and pay through the composed Claude parser."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg import Connection

from jobhunt.composition import COMPOSITION, require_on_machine
from jobhunt.core.log import get_logger
from jobhunt.core.paths import API_ROOT
from jobhunt.facts.apply import posting_input
from jobhunt.facts.base import JobDetail
from jobhunt.facts.claude import ClaudeParser
from jobhunt.facts.contract import check_facts
from jobhunt.facts.coverage import coverage_table
from jobhunt.facts.merge import merge_facts, save_facts
from jobhunt.scrape.sources.base import RawPosting

log = get_logger("facts")

_BACKUP = "jobs_facts_backup_20261012"
_BATCH = 200
_SPOT = 30
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
    "locations",
    "countries",
    "role",
    "level",
)
_REQUIRED = """
j.role IS NULL OR j.country IS NULL OR j.locations = '[]'::jsonb OR j.level = 'unknown'
"""
_PAY_ONLY = """
j.role IS NOT NULL AND j.country IS NOT NULL AND j.locations <> '[]'::jsonb
AND j.level <> 'unknown' AND j.salary_min IS NULL AND j.salary_max IS NULL
"""
_FRESH = """
p.facts_status <> 'failed'
AND COALESCE(p.facts->>'parsed_by', '') <> %s
AND NOT EXISTS (
    SELECT 1 FROM jsonb_each(COALESCE(p.facts, '{}'::jsonb)) AS entry
    WHERE jsonb_typeof(entry.value) = 'object'
      AND entry.value->>'parser_id' = %s
)
"""
_FAILED = "p.facts_status = 'failed'"


def run_backfill(
    conn: Connection[Any],
    *,
    dry_run: bool = False,
    restore: bool = False,
    limit: int | None = None,
    retry_failed: bool = False,
    checkpoint: Path | None = None,
    report_dir: Path | None = None,
) -> str:
    if restore:
        _restore(conn)
        conn.commit()
        return "restored"
    parser = _require_parser()
    _snapshot(conn)
    conn.commit()
    before = coverage_table(conn)
    tried, reasons, spot, spent = _fill(
        conn,
        parser,
        dry_run=dry_run,
        limit=limit,
        retry_failed=retry_failed,
        checkpoint=checkpoint or _checkpoint_path(),
    )
    after = coverage_table(conn)
    if dry_run:
        conn.rollback()
        after = f"{after}\n(rolled back)"
    report = _report(before, after, reasons, spot, spent, tried)
    if report_dir is not None or not dry_run:
        directory = report_dir or (API_ROOT / "reports")
        directory.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = directory / f"facts_backfill_{stamp}.md"
        path.write_text(report)
        return f"{path}\n\n{report}"
    return report


def _require_parser() -> ClaudeParser:
    parser = COMPOSITION.parser
    if not isinstance(parser, ClaudeParser):
        raise ValueError("backfill requires COMPOSITION.parser to be ClaudeParser")
    require_on_machine(parser, "parser")
    return parser


def _snapshot(conn: Connection[Any]) -> None:
    columns = ", ".join(_COLUMNS)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_BACKUP} AS
        SELECT id, {columns} FROM jobs WHERE false
        """
    )
    exists = conn.execute(f"SELECT 1 FROM {_BACKUP} LIMIT 1").fetchone()
    if exists is not None:
        return
    conn.execute(
        f"""
        INSERT INTO {_BACKUP} (id, {columns})
        SELECT id, {columns} FROM jobs
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


def _fill(
    conn: Connection[Any],
    parser: ClaudeParser,
    *,
    dry_run: bool,
    limit: int | None,
    retry_failed: bool,
    checkpoint: Path,
) -> tuple[list[int], list[tuple[int, str, str]], list[str], Decimal]:
    band, last = (0, 0) if dry_run or retry_failed else _read_checkpoint(checkpoint)
    tried: list[int] = []
    reasons: list[tuple[int, str, str]] = []
    spot: list[str] = []
    spent = Decimal(0)
    while True:
        if limit is not None and len(tried) >= limit:
            break
        room = _BATCH if limit is None else min(_BATCH, limit - len(tried))
        jobs = _next_jobs(conn, band, last, parser.parser_id, retry_failed, room)
        if not jobs and band == 0:
            band, last = 1, 0
            continue
        if not jobs:
            break
        for job_id in jobs:
            cost, job_reasons, line = _one(conn, parser, job_id, retry_failed)
            spent += cost
            tried.append(job_id)
            reasons.extend(job_reasons)
            if line is not None and len(spot) < _SPOT:
                spot.append(line)
            last = job_id
            if dry_run:
                print(f"backfill job {job_id} cost_usd {cost}", flush=True)
        if dry_run:
            continue
        conn.commit()
        if not retry_failed:
            _write_checkpoint(checkpoint, band, last)
        print(f"backfill {len(tried)} jobs cost_usd {spent}", flush=True)
    return tried, reasons, spot, spent


def _next_jobs(
    conn: Connection[Any],
    band: int,
    after_id: int,
    parser_id: str,
    retry_failed: bool,
    room: int,
) -> list[int]:
    eligible = _FAILED if retry_failed else _FRESH
    gap = _REQUIRED if band == 0 else _PAY_ONLY
    params: tuple[object, ...] = (after_id, parser_id, parser_id, room)
    if retry_failed:
        params = (after_id, room)
    rows = conn.execute(
        f"""
        SELECT j.id
        FROM jobs j
        WHERE j.closed_at IS NULL
          AND j.id > %s
          AND ({gap})
          AND EXISTS (
            SELECT 1 FROM postings p
            WHERE p.job_id = j.id AND ({eligible})
          )
        ORDER BY j.id
        LIMIT %s
        """,
        params,
    ).fetchall()
    return [int(row[0]) for row in rows]


def _one(
    conn: Connection[Any], parser: ClaudeParser, job_id: int, retry_failed: bool
) -> tuple[Decimal, list[tuple[int, str, str]], str | None]:
    eligible = _FAILED if retry_failed else _FRESH
    params: tuple[object, ...] = (job_id, parser.parser_id, parser.parser_id)
    if retry_failed:
        params = (job_id,)
    rows = conn.execute(
        f"""
        SELECT p.id, p.source_id, p.source_job_id, p.source_url, j.title,
               j.description_md, j.city, j.country, j.employment_type, rp.payload
        FROM postings p
        JOIN jobs j ON j.id = p.job_id
        LEFT JOIN LATERAL (
            SELECT payload FROM raw_payloads r
            WHERE r.posting_id = p.id
            ORDER BY fetched_at DESC
            LIMIT 1
        ) rp ON true
        WHERE p.job_id = %s AND ({eligible})
        """,
        params,
    ).fetchall()
    before = _state(conn, job_id)
    drops: list[tuple[str, str]] = []
    error: str | None = None
    spent = Decimal(0)
    for row in rows:
        cost, failed = _parse_posting(conn, parser, row, drops)
        spent += cost
        if failed is not None:
            error = failed
    merge_facts(conn, job_id)
    after = _state(conn, job_id)
    still_open = _gaps(after) & _gaps(before)
    reasons = [(job_id, field, _reason(field, drops, error)) for field in still_open]
    return spent, reasons, _spot_line(job_id, before, after)


def _parse_posting(
    conn: Connection[Any],
    parser: ClaudeParser,
    row: tuple[Any, ...],
    drops: list[tuple[str, str]],
) -> tuple[Decimal, str | None]:
    (
        posting_id,
        source_id,
        source_job_id,
        source_url,
        title,
        description,
        city,
        country,
        employment,
        payload,
    ) = row
    body = payload if isinstance(payload, dict) else {}
    place = ", ".join(part for part in (city, country) if isinstance(part, str) and part)
    item = posting_input(
        RawPosting(
            source_id=str(source_id),
            source_job_id=str(source_job_id),
            source_url=str(source_url),
            company_name="",
            title=str(title or ""),
            location_raw=place or None,
            employment_type_raw=employment if isinstance(employment, str) else None,
            payload=body,
        ),
        description if isinstance(description, str) else "",
    )
    start = len(parser.calls)
    try:
        parsed = check_facts(
            parser.parse(item),
            title=item.title,
            description=item.description_md,
            drops=drops,
        )
        status = "done"
        error = None
    except Exception as exc:
        log.warning("parser failed: %s", type(exc).__name__)
        parsed = JobDetail()
        status = "failed"
        error = type(exc).__name__
    save_facts(conn, int(posting_id), parsed, status)
    if status == "done":
        conn.execute(
            """
            UPDATE postings
            SET facts = COALESCE(facts, '{}'::jsonb)
                || jsonb_build_object('parsed_by', %s::text)
            WHERE id = %s
            """,
            (parser.parser_id, int(posting_id)),
        )
    added = parser.calls[start:]
    return sum((meta.cost_usd for meta in added), Decimal(0)), error


def _state(conn: Connection[Any], job_id: int) -> tuple[Any, ...]:
    row = conn.execute(
        """
        SELECT title, role, level, country, locations, salary_min, salary_max
        FROM jobs WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"job {job_id} disappeared during backfill")
    return tuple(row)


def _gaps(state: tuple[Any, ...]) -> set[str]:
    _title, role, level, country, locations, salary_min, salary_max = state
    gaps: set[str] = set()
    if role is None:
        gaps.add("role")
    if level in (None, "unknown"):
        gaps.add("level")
    if country is None or locations in (None, [], "[]"):
        gaps.add("location")
    if salary_min is None and salary_max is None:
        gaps.add("pay")
    return gaps


def _reason(field: str, drops: list[tuple[str, str]], error: str | None) -> str:
    if error is not None:
        return f"API error: {error}"
    names = {"location": "locations"}
    wanted = names.get(field, field)
    for dropped, rule in drops:
        if dropped == wanted:
            return f"contract drop: {rule}"
    return "no evidence"


def _spot_line(job_id: int, before: tuple[Any, ...], after: tuple[Any, ...]) -> str:
    title = str(after[0] or "").replace("\n", " ")
    return (
        f"{job_id} | {title} | role {before[1]} -> {after[1]} | "
        f"level {before[2]} -> {after[2]} | country {before[3]} -> {after[3]} | "
        f"pay {before[5]} -> {after[5]}"
    )


def _report(
    before: str,
    after: str,
    reasons: list[tuple[int, str, str]],
    spot: list[str],
    spent: Decimal,
    tried: list[int],
) -> str:
    gap_lines = [f"{job_id}\t{field}\t{reason}" for job_id, field, reason in reasons] or ["none"]
    spot_lines = spot or ["none"]
    return "\n".join(
        (
            f"tried {len(tried)}",
            f"cost_usd {spent}",
            "",
            "before",
            before,
            "",
            "after",
            after,
            "",
            "remaining gaps",
            "job_id\tfield\treason",
            *gap_lines,
            "",
            f"spot check ({len(spot)})",
            *spot_lines,
            "",
        )
    )


def _checkpoint_path() -> Path:
    directory = API_ROOT / "reports"
    directory.mkdir(exist_ok=True)
    return directory / "facts_backfill.checkpoint"


def _read_checkpoint(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    text = path.read_text().strip()
    if not text:
        return 0, 0
    if "," not in text:
        return 0, int(text)
    band, job_id = text.split(",", 1)
    return int(band), int(job_id)


def _write_checkpoint(path: Path, band: int, job_id: int) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(f"{band},{job_id}")

"""The database rejects a bad salary or experience, and USD is computed at read time."""

from pathlib import Path

import psycopg
import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db"
    / "migrations"
    / "20261015000019_job_compensation.sql"
)


def test_database_rejects_bad_compensation(conn) -> None:
    job_id = _job(conn, "pay co")
    _reject(conn, _insert(job_id, currency="thb"))
    _reject(conn, _insert(job_id, min_amount=0))
    _reject(conn, _insert(job_id, min_amount=80, max_amount=40))
    _reject(conn, _insert(job_id, min_amount=None, max_amount=None))
    _reject(conn, _insert(job_id, unit=None, units_per_year=12))
    once = _job(conn, "once co")
    _reject(
        conn,
        _insert(once, unit="one_time", units_per_year=1, parser_id="api:seek", evidence=None),
    )
    _reject(conn, _insert(job_id, evidence=None, parser_id="claude-haiku-5-5/v2"))
    _reject(conn, _insert(job_id, evidence="", parser_id="api:seek"))
    _base(conn, job_id)
    _reject(conn, _insert(job_id))
    _reject(conn, "UPDATE jobs SET experience_min_months = 900 WHERE id = %s", (job_id,))
    _reject(
        conn,
        "UPDATE jobs SET experience_min_months = 60, experience_max_months = 12 WHERE id = %s",
        (job_id,),
    )
    _reject(conn, "UPDATE jobs SET experience_max_months = 12 WHERE id = %s", (job_id,))


def test_annual_and_usd_come_from_the_row(conn) -> None:
    job_id = _job(conn, "annual co")
    _base(conn, job_id)
    annual = conn.execute(
        "SELECT annual_min FROM job_compensation WHERE job_id = %s", (job_id,)
    ).fetchone()
    assert annual == (480000,)
    conn.execute(
        """
        UPDATE fx_rates SET usd_per_unit = 0.03, as_of = DATE '2026-10-15'
        WHERE currency = 'THB'
        """
    )
    usd = conn.execute(
        "SELECT usd_annual_min FROM job_base_pay WHERE job_id = %s", (job_id,)
    ).fetchone()
    assert usd == (14400,)
    conn.execute("UPDATE fx_rates SET usd_per_unit = 0.04 WHERE currency = 'THB'")
    changed = conn.execute(
        "SELECT usd_annual_min FROM job_base_pay WHERE job_id = %s", (job_id,)
    ).fetchone()
    assert changed == (19200,)


def test_copy_keeps_good_pay_and_skips_bad_pay(conn) -> None:
    good = _salary_job(conn, "good", minimum=40000, maximum=40000, evidence="40000 per month")
    _salary_job(conn, "zero", minimum=0, maximum=0, evidence="0")
    _salary_job(conn, "bare", minimum=50000, maximum=50000, evidence=None)
    api = _salary_job(
        conn, "api", minimum=80000, maximum=90000, evidence=None, origin="api:greenhouse"
    )
    conn.execute(_copy_sql())
    rows = conn.execute(
        "SELECT job_id, evidence IS NULL, parser_id FROM job_compensation ORDER BY job_id"
    ).fetchall()
    assert rows == [(good, False, "claude/v1"), (api, True, "api:greenhouse")]


def _job(conn, name: str) -> int:
    company = conn.execute(
        "INSERT INTO companies (name, name_norm) VALUES (%s, %s) RETURNING id",
        (name, name),
    ).fetchone()
    assert company is not None
    job = conn.execute(
        """
        INSERT INTO jobs (company_id, title, title_norm, apply_url, dedupe_key)
        VALUES (%s, 'Engineer', 'engineer', 'https://example.com/j', %s)
        RETURNING id
        """,
        (company[0], f"pay-co|{company[0]}"),
    ).fetchone()
    assert job is not None
    return int(job[0])


def _salary_job(
    conn,
    name: str,
    *,
    minimum: int,
    maximum: int,
    evidence: str | None,
    origin: str = "claude/v1",
) -> int:
    company = conn.execute(
        "INSERT INTO companies (name, name_norm) VALUES (%s, %s) RETURNING id",
        (name, name),
    ).fetchone()
    assert company is not None
    job = conn.execute(
        """
        INSERT INTO jobs (
          company_id, title, title_norm, apply_url, dedupe_key,
          salary_min, salary_max, salary_currency, salary_interval, fact_origins
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'THB', 'monthly', %s::jsonb)
        RETURNING id
        """,
        (
            company[0],
            name,
            name,
            f"https://example.com/{name}",
            f"{name}|{company[0]}",
            minimum,
            maximum,
            f'{{"pay": "{origin}"}}',
        ),
    ).fetchone()
    assert job is not None
    job_id = int(job[0])
    facts = '{"pay": {}}' if evidence is None else f'{{"pay": {{"evidence": "{evidence}"}}}}'
    conn.execute(
        """
        INSERT INTO postings (job_id, source_id, source_job_id, source_url, content_hash, facts)
        VALUES (%s, 'greenhouse', %s, %s, %s, %s::jsonb)
        """,
        (job_id, name, f"https://example.com/{name}", name, facts),
    )
    return job_id


def _base(conn, job_id: int) -> None:
    sql, params = _insert(job_id)
    conn.execute(sql, params)


def _insert(
    job_id: int,
    *,
    currency: str = "THB",
    min_amount: int | None = 40000,
    max_amount: int | None = 40000,
    unit: str | None = "monthly",
    units_per_year: int | None = 12,
    evidence: str | None = "40000 per month",
    parser_id: str = "claude-haiku-5-5/v2",
) -> tuple[str, tuple[object, ...]]:
    return (
        """
        INSERT INTO job_compensation (
          job_id, type, unit, currency, min_amount, max_amount, units_per_year, evidence, parser_id
        )
        VALUES (%s, 'base', %s, %s, %s, %s, %s, %s, %s)
        """,
        (job_id, unit, currency, min_amount, max_amount, units_per_year, evidence, parser_id),
    )


def _reject(
    conn,
    sql: str | tuple[str, tuple[object, ...]],
    params: tuple[object, ...] = (),
) -> None:
    statement, bound = sql if isinstance(sql, tuple) else (sql, params)
    with pytest.raises(psycopg.Error):
        with conn.transaction():
            conn.execute(statement, bound)


def _copy_sql() -> str:
    text = _MIGRATION.read_text()
    start = text.index("-- copy:begin") + len("-- copy:begin")
    end = text.index("-- copy:end")
    return text[start:end]

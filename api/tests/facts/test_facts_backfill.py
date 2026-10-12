"""Backfill fills empty columns through ClaudeParser and leaves stored values alone."""

from dataclasses import replace
from decimal import Decimal

import pytest
from jobhunt.composition import COMPOSITION
from jobhunt.core.claude import CallMeta, ClaudeRefusal
from jobhunt.facts import backfill as backfill_mod
from jobhunt.facts.base import JobDetail, LocationFact, ParseHints, Place, PostingInput, TextFact
from jobhunt.facts.claude import ClaudeParser
from jobhunt.scrape import repo


class StubParser(ClaudeParser):
    def __init__(self, *, fail: bool = False, bad_evidence: bool = False) -> None:
        super().__init__()
        self.fail = fail
        self.bad_evidence = bad_evidence
        self.seen: list[str] = []

    def parse(self, posting: PostingInput, hints: ParseHints | None = None) -> JobDetail:
        del hints
        self.seen.append(posting.title)
        self.calls.append(
            CallMeta(
                model=self.model,
                input_tokens=100,
                output_tokens=20,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost_usd=Decimal("0.00002000"),
            )
        )
        if self.fail:
            raise ClaudeRefusal("no")
        evidence = "missing" if self.bad_evidence else posting.title
        return JobDetail(
            role=TextFact(
                value="software", confidence=1, evidence=evidence, parser_id=self.parser_id
            ),
            level=TextFact(
                value="senior", confidence=1, evidence=evidence, parser_id=self.parser_id
            ),
            locations=LocationFact(
                value=[Place(city="Austin", country="US")],
                confidence=1,
                evidence=evidence,
                parser_id=self.parser_id,
            ),
        )


def _reset(conn) -> None:
    conn.execute("DROP TABLE IF EXISTS jobs_facts_backup_20261012")
    conn.commit()


def _job(
    conn, company_id: int, title: str, *, role: str | None = None, level: str = "unknown"
) -> int:
    return repo.insert_job(
        conn,
        company_id=company_id,
        title=title,
        title_norm=title.lower(),
        apply_url=f"https://example.com/{title}",
        dedupe_key=f"{company_id}|{title.lower()}|??",
        description_md=title,
        role=role,
        level=level,
    )


def _posting(conn, job_id: int, source_job_id: str) -> int:
    return repo.insert_posting(
        conn,
        job_id=job_id,
        source_id="greenhouse",
        source_job_id=source_job_id,
        source_url=f"https://example.com/{source_job_id}",
        content_hash=source_job_id,
    )


def test_backfill_refuses_unless_claude_parser(conn, monkeypatch) -> None:
    monkeypatch.setattr(backfill_mod, "COMPOSITION", COMPOSITION)
    monkeypatch.delenv("JOBHUNT_ALLOW_OFFSITE", raising=False)
    with pytest.raises(ValueError, match="ClaudeParser"):
        backfill_mod.run_backfill(conn, limit=1)


def test_backfill_fills_gaps_and_keeps_stored_role(committed, monkeypatch, tmp_path) -> None:
    _reset(committed)
    monkeypatch.setenv("JOBHUNT_ALLOW_OFFSITE", "1")
    parser = StubParser()
    monkeypatch.setattr(backfill_mod, "COMPOSITION", replace(COMPOSITION, parser=parser))
    company_id = repo.insert_company(committed, name="Backfill Co", name_norm="backfill co")
    missing = _job(committed, company_id, "Senior Engineer")
    _posting(committed, missing, "bf-missing")
    kept = _job(committed, company_id, "Backend Lead", role="backend")
    _posting(committed, kept, "bf-kept")
    pay_only = _job(committed, company_id, "Staff Engineer", role="software", level="staff")
    pay_posting = _posting(committed, pay_only, "bf-pay")
    committed.execute(
        """
        UPDATE jobs
        SET country = 'US', locations = '[{"city": "Austin", "country": "US"}]'::jsonb
        WHERE id = %s
        """,
        (pay_only,),
    )
    committed.execute(
        "UPDATE postings SET facts = %s::jsonb WHERE id = %s",
        ('{"parsed_by": "claude-haiku-5-5/v1"}', pay_posting),
    )
    committed.commit()

    preview = backfill_mod.run_backfill(
        committed,
        dry_run=True,
        limit=1,
        checkpoint=tmp_path / "dry.checkpoint",
        report_dir=tmp_path,
    )
    assert "cost_usd" in preview
    still = committed.execute("SELECT role FROM jobs WHERE id = %s", (missing,)).fetchone()
    assert still is not None and still[0] is None

    report = backfill_mod.run_backfill(
        committed,
        limit=1,
        checkpoint=tmp_path / "run.checkpoint",
        report_dir=tmp_path,
    )
    filled = committed.execute(
        "SELECT role, level, country FROM jobs WHERE id = %s", (missing,)
    ).fetchone()
    assert filled == ("software", "senior", "US")
    kept_row = committed.execute("SELECT role, level FROM jobs WHERE id = %s", (kept,)).fetchone()
    assert kept_row == ("backend", "unknown")
    assert parser.seen == ["Senior Engineer", "Senior Engineer"]
    assert "no evidence" in report
    assert "spot check" in report

    backfill_mod.run_backfill(committed, restore=True)
    restored = committed.execute("SELECT role FROM jobs WHERE id = %s", (missing,)).fetchone()
    assert restored is not None and restored[0] is None
    _reset(committed)


def test_contract_drop_and_api_retry(committed, monkeypatch, tmp_path) -> None:
    _reset(committed)
    monkeypatch.setenv("JOBHUNT_ALLOW_OFFSITE", "1")
    company_id = repo.insert_company(committed, name="Backfill Fail", name_norm="backfill fail")
    dropped = _job(committed, company_id, "Dropped Role")
    _posting(committed, dropped, "bf-drop")
    committed.commit()

    drop_parser = StubParser(bad_evidence=True)
    monkeypatch.setattr(backfill_mod, "COMPOSITION", _compose(drop_parser))
    report = backfill_mod.run_backfill(
        committed, checkpoint=tmp_path / "drop.checkpoint", report_dir=tmp_path
    )
    assert "contract drop: evidence" in report
    again = len(drop_parser.seen)
    backfill_mod.run_backfill(
        committed, checkpoint=tmp_path / "drop-again.checkpoint", report_dir=tmp_path
    )
    assert len(drop_parser.seen) == again

    failed = _job(committed, company_id, "Failed Role")
    failed_posting = _posting(committed, failed, "bf-fail")
    committed.commit()
    fail_parser = StubParser(fail=True)
    monkeypatch.setattr(backfill_mod, "COMPOSITION", _compose(fail_parser))
    failed_report = backfill_mod.run_backfill(
        committed, checkpoint=tmp_path / "fail.checkpoint", report_dir=tmp_path
    )
    assert "API error: ClaudeRefusal" in failed_report
    status = committed.execute(
        "SELECT facts_status FROM postings WHERE id = %s", (failed_posting,)
    ).fetchone()
    assert status == ("failed",)
    calls = len(fail_parser.seen)
    backfill_mod.run_backfill(
        committed, checkpoint=tmp_path / "fail-skip.checkpoint", report_dir=tmp_path
    )
    assert len(fail_parser.seen) == calls
    fail_parser.fail = False
    backfill_mod.run_backfill(
        committed,
        retry_failed=True,
        checkpoint=tmp_path / "retry.checkpoint",
        report_dir=tmp_path,
    )
    retried = committed.execute("SELECT role FROM jobs WHERE id = %s", (failed,)).fetchone()
    assert retried == ("software",)
    _reset(committed)


def _compose(parser: ClaudeParser):
    return replace(COMPOSITION, parser=parser)

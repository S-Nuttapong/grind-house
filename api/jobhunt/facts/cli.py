"""jobhunt facts: benchmark, decide, and backfill."""

from __future__ import annotations

from pathlib import Path

import typer

from jobhunt.facts.eval import ParserCase

facts_app = typer.Typer(no_args_is_help=True, help="Job detail parsers.")

_GOLD = typer.Option(Path("evals/gold/parser.jsonl"), "--gold", help="Gitignored gold JSONL.")
_GOLD_OUT = typer.Option(Path("evals/gold/parser.jsonl"), "--out")


@facts_app.command("bench")
def bench(sample: int | None = typer.Option(None, "--sample", help="Stratified row cap.")) -> None:
    """Score default, gliner, and default+gliner. Writes api/reports/facts_bench_*."""
    from jobhunt.core.db import pool
    from jobhunt.facts.bench import run_bench

    conn = pool().getconn()
    try:
        path = run_bench(conn, sample=sample)
    finally:
        pool().putconn(conn)
    typer.echo(path)


_REPORT = typer.Argument(..., help="facts_bench JSON from the bench command.")


@facts_app.command("decide")
def decide(report: Path = _REPORT) -> None:
    """Write config/facts.yaml from a bench report."""
    from jobhunt.facts.decide import write_config

    if not report.is_file():
        typer.echo(f"report not found: {report}", err=True)
        raise typer.Exit(code=1)
    typer.echo(write_config(report))


@facts_app.command("fx-sync")
def fx_sync() -> None:
    """Upsert fx_rates from Frankfurter, then open.er-api for the rest."""
    from jobhunt.core.db import tx
    from jobhunt.scrape.normalize.fx import sync_fx

    try:
        with tx() as conn:
            count = sync_fx(conn)
    except Exception as exc:
        typer.echo(f"fx sync failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"fx rates upserted: {count}")


@facts_app.command("backfill")
def backfill(
    dry_run: bool = typer.Option(False, "--dry-run"),
    restore: bool = typer.Option(False, "--restore"),
    limit: int | None = typer.Option(None, "--limit"),
    retry_failed: bool = typer.Option(False, "--retry-failed"),
) -> None:
    """Fill empty role, location, level, and pay. Pay is best effort."""
    from jobhunt.core.db import pool
    from jobhunt.facts.backfill import run_backfill

    conn = pool().getconn()
    try:
        typer.echo(
            run_backfill(
                conn, dry_run=dry_run, restore=restore, limit=limit, retry_failed=retry_failed
            )
        )
    finally:
        pool().putconn(conn)


@facts_app.command("reparse")
def reparse(
    source: str | None = typer.Option(None, "--source", help="Limit to one source id."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Re-run the composed parser on open postings. Prints coverage before and after."""
    from jobhunt.core.db import pool
    from jobhunt.facts.reparse import run_reparse

    conn = pool().getconn()
    try:
        typer.echo(run_reparse(conn, source=source, dry_run=dry_run))
    finally:
        pool().putconn(conn)


@facts_app.command("eval")
def evaluate(
    gold: Path = _GOLD,
    llm: str | None = typer.Option(None, "--llm", help="Provider instead of the composed parser."),
) -> None:
    """Score COMPOSITION.parser on the gold file and apply the gates."""
    from jobhunt.composition import COMPOSITION, job_facts_parser, require_on_machine
    from jobhunt.facts.eval import eval_parser, load_gold, parser_gates

    if not gold.is_file():
        typer.echo(f"no gold file at {gold}", err=True)
        raise typer.Exit(code=1)
    parser = job_facts_parser(llm) if llm is not None else COMPOSITION.parser
    require_on_machine(parser, "parser")
    report = eval_parser(parser, load_gold(gold))
    _print_parser_report(report)
    failures = parser_gates(report)
    for failure in failures:
        typer.echo(failure, err=True)
    if failures:
        raise typer.Exit(code=1)


@facts_app.command("gold-draft")
def gold_draft(
    limit: int = typer.Option(150, "--limit"),
    out: Path = _GOLD_OUT,
) -> None:
    """Write a gold file from payload facts for a person to verify. Not committed."""
    from jobhunt.core.db import tx
    from jobhunt.facts.eval import write_gold

    with tx() as conn:
        rows = conn.execute(
            """
            SELECT j.id, j.title, j.description_md, j.role, j.level, j.country, j.city,
                   j.remote, j.employment_type, bp.min_amount, bp.max_amount,
                   bp.currency, bp.unit, p.source_id, rp.payload
            FROM jobs j
            LEFT JOIN job_base_pay bp ON bp.job_id = j.id
            JOIN postings p ON p.job_id = j.id
            JOIN LATERAL (
                SELECT payload FROM raw_payloads r
                WHERE r.posting_id = p.id
                ORDER BY fetched_at DESC
                LIMIT 1
            ) rp ON true
            WHERE j.description_md IS NOT NULL
            ORDER BY j.id
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    cases = [_draft_case(row) for row in rows]
    write_gold(out, cases)
    typer.echo(f"wrote {len(cases)} cases to {out}")


def _draft_case(row: tuple[object, ...]) -> ParserCase:
    from jobhunt.facts.api_fields import from_payload
    from jobhunt.facts.base import JobDetail, PostingInput, prefer

    (
        job_id,
        title,
        description,
        role,
        level,
        country,
        city,
        remote,
        employment,
        salary_min,
        salary_max,
        salary_currency,
        salary_interval,
        source_id,
        payload,
    ) = row
    body = payload if isinstance(payload, dict) else {}
    title_text = str(title or "")
    stored = JobDetail(
        role=_draft_text(role, title_text),
        level=_draft_text(None if level in (None, "unknown") else level, title_text),
        workplace=_draft_text(None if remote in (None, "unknown") else remote, title_text),
        job_type=_draft_text(employment, title_text),
        locations=_draft_location(country, city),
        pay=_draft_pay(salary_min, salary_max, salary_currency, salary_interval),
    )
    return ParserCase(
        case_id=str(job_id),
        posting=PostingInput(title=title_text, description_md=str(description or "")),
        expected=prefer(from_payload(str(source_id), body), stored),
    )


def _draft_text(value: object, evidence: str) -> object:
    from jobhunt.facts.base import TextFact

    if not isinstance(value, str) or not value:
        return None
    return TextFact(value=value, confidence=1, evidence=evidence or value, parser_id="gold")


def _draft_location(country: object, city: object) -> object:
    from jobhunt.facts.base import LocationFact, Place

    if not isinstance(country, str) or not country:
        return None
    return LocationFact(
        value=[Place(country=country, city=city if isinstance(city, str) and city else None)],
        confidence=1,
        evidence=country,
        parser_id="gold",
    )


def _draft_pay(minimum: object, maximum: object, currency: object, interval: object) -> object:
    from decimal import Decimal

    from jobhunt.facts.base import Pay, PayFact

    if minimum is None and maximum is None:
        return None
    return PayFact(
        value=Pay(
            minimum=None if minimum is None else Decimal(str(minimum)),
            maximum=None if maximum is None else Decimal(str(maximum)),
            currency=currency if isinstance(currency, str) else None,
            interval=interval if isinstance(interval, str) else None,
        ),
        confidence=1,
        evidence="pay",
        parser_id="gold",
    )


def _print_parser_report(report: object) -> None:
    from jobhunt.facts.eval import ParserReport, latency_p50, latency_p95

    if not isinstance(report, ParserReport):
        return
    typer.echo(f"cases: {report.cases} errors: {report.errors}")
    typer.echo(f"precision: {report.precision}")
    typer.echo(f"recall: {report.recall}")
    typer.echo(f"hallucination: {report.hallucination}")
    typer.echo(f"ece: {report.ece}")
    typer.echo(f"schema_valid: {report.schema_valid_rate}")
    p50 = latency_p50(report)
    p95 = latency_p95(report)
    typer.echo(f"p50: {p50} p95: {p95} cost_usd: {report.cost_usd}")
    for name, score in report.fields.items():
        typer.echo(
            f"  {name}: correct={score.correct} missing={score.missing} "
            f"wrong={score.wrong} hallucinated={score.hallucinated}"
        )


@facts_app.command("coverage")
def coverage() -> None:
    """Print missing Job details per source."""
    from jobhunt.core.db import tx
    from jobhunt.facts.coverage import coverage_table

    with tx() as conn:
        typer.echo(coverage_table(conn))

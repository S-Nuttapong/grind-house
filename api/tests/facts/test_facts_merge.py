"""merge_facts never overwrites a value the source already stored."""

from decimal import Decimal

from jobhunt.facts.base import (
    Experience,
    ExperienceFact,
    JobDetail,
    LocationFact,
    Pay,
    PayFact,
    Place,
    TextFact,
)
from jobhunt.facts.merge import merge_facts, save_facts
from jobhunt.scrape import repo


def test_merge_fills_nulls_and_keeps_source_values(conn) -> None:
    company_id = repo.insert_company(conn, name="Acme", name_norm="acme-facts")
    job_id = repo.insert_job(
        conn,
        company_id=company_id,
        title="Engineer",
        title_norm="engineer",
        apply_url="https://example.com/1",
        dedupe_key=f"{company_id}|engineer|??",
        country="US",
        remote="unknown",
    )
    posting_id = repo.insert_posting(
        conn,
        job_id=job_id,
        source_id="greenhouse",
        source_job_id="facts-1",
        source_url="https://example.com/1",
        content_hash="abc",
    )
    save_facts(
        conn,
        posting_id,
        JobDetail(
            pay=PayFact(
                value=Pay(
                    minimum=Decimal("100000"),
                    maximum=Decimal("120000"),
                    currency="USD",
                    interval="yearly",
                ),
                confidence=1,
                evidence="100000",
                parser_id="api:greenhouse",
            ),
            workplace=TextFact(
                value="hybrid", confidence=1, evidence="Hybrid", parser_id="api:greenhouse"
            ),
            locations=LocationFact(
                value=[Place(city="Austin", country="PT")],
                confidence=1,
                evidence="Austin",
                parser_id="default",
            ),
        ),
        "done",
    )
    merge_facts(conn, job_id)
    row = conn.execute(
        "SELECT country, city, remote, salary_min, fact_origins FROM jobs WHERE id = %s",
        (job_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "US"
    assert row[1] == "Austin"
    assert row[2] == "hybrid"
    assert row[3] == Decimal("100000")
    assert row[4]["workplace"] == "api:greenhouse"
    assert row[4]["locations"] == "default"


def test_merge_fills_experience_when_the_job_has_none(conn) -> None:
    company_id = repo.insert_company(conn, name="Gamma", name_norm="gamma-facts")
    job_id = repo.insert_job(
        conn,
        company_id=company_id,
        title="Engineer",
        title_norm="engineer",
        apply_url="https://example.com/3",
        dedupe_key=f"{company_id}|engineer|??",
    )
    posting_id = repo.insert_posting(
        conn,
        job_id=job_id,
        source_id="greenhouse",
        source_job_id="facts-exp",
        source_url="https://example.com/3",
        content_hash="abc",
    )
    save_facts(
        conn,
        posting_id,
        JobDetail(
            experience=ExperienceFact(
                value=Experience(minimum=5, maximum=8),
                confidence=1,
                evidence="5-8 years",
                parser_id="default",
            )
        ),
        "done",
    )
    merge_facts(conn, job_id)
    row = conn.execute(
        """
        SELECT experience_min_years, experience_max_years, fact_origins
        FROM jobs WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == 5
    assert row[1] == 8
    assert row[2]["experience"] == "default"


def test_chain_order_prefers_api_over_default(conn) -> None:
    company_id = repo.insert_company(conn, name="Beta", name_norm="beta-facts")
    job_id = repo.insert_job(
        conn,
        company_id=company_id,
        title="Engineer",
        title_norm="engineer",
        apply_url="https://example.com/2",
        dedupe_key=f"{company_id}|engineer|??",
        remote="unknown",
    )
    first = repo.insert_posting(
        conn,
        job_id=job_id,
        source_id="greenhouse",
        source_job_id="facts-2",
        source_url="https://example.com/2",
        content_hash="abc",
    )
    second = repo.insert_posting(
        conn,
        job_id=job_id,
        source_id="lever",
        source_job_id="facts-3",
        source_url="https://example.com/3",
        content_hash="def",
    )
    save_facts(
        conn,
        first,
        JobDetail(
            workplace=TextFact(
                value="remote", confidence=0.99, evidence="remote", parser_id="default"
            )
        ),
        "done",
    )
    save_facts(
        conn,
        second,
        JobDetail(
            workplace=TextFact(
                value="hybrid", confidence=0.4, evidence="hybrid", parser_id="api:lever"
            )
        ),
        "done",
    )
    merge_facts(conn, job_id)
    row = conn.execute("SELECT remote, fact_origins FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert row is not None
    assert row[0] == "hybrid"
    assert row[1]["workplace"] == "api:lever"

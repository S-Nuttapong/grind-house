"""Contract checks drop a bad field and keep the rest."""

from datetime import date, timedelta
from decimal import Decimal

from jobhunt.facts.base import DateFact, JobDetail, LocationFact, Pay, PayFact, Place, TextFact
from jobhunt.facts.contract import check_facts

_TODAY = date(2026, 10, 12)


def _text(value: str, evidence: str, parser_id: str = "default") -> TextFact:
    return TextFact(value=value, confidence=1, evidence=evidence, parser_id=parser_id)


def test_evidence_must_be_in_the_posting_unless_it_came_from_the_source() -> None:
    detail = JobDetail(
        role=_text("software", "not in the text"),
        level=_text("senior", "Senior", parser_id="api:posting"),
    )
    checked = check_facts(
        detail, title="Senior engineer", description="Build things.", today=_TODAY
    )
    assert checked.role is None
    assert checked.level is not None
    assert checked.level.value == "senior"


def test_pay_outside_the_band_or_currency_is_dropped() -> None:
    text = "Salary: 100000 USD per year"
    good = PayFact(
        value=Pay(
            minimum=Decimal("100000"),
            maximum=Decimal("120000"),
            currency="USD",
            interval="yearly",
        ),
        confidence=1,
        evidence="100000 USD",
        parser_id="default",
    )
    bad = PayFact(
        value=Pay(minimum=Decimal("1"), maximum=Decimal("2"), currency="USD", interval="yearly"),
        confidence=1,
        evidence="1",
        parser_id="default",
    )
    kept = check_facts(JobDetail(pay=good), title="", description=text, today=_TODAY)
    assert kept.pay is not None
    assert check_facts(JobDetail(pay=bad), title="1", description="", today=_TODAY).pay is None


def _posted(day: date, evidence: str) -> DateFact:
    return DateFact(value=day, confidence=1, evidence=evidence, parser_id="api:posting")


def test_posted_in_the_future_or_too_old_is_dropped() -> None:
    future = _posted(_TODAY + timedelta(days=1), "tomorrow")
    old = _posted(_TODAY - timedelta(days=400), "old")
    recent = _posted(_TODAY - timedelta(days=3), "recent")
    future_detail = check_facts(JobDetail(posted=future), title="", description="", today=_TODAY)
    old_detail = check_facts(JobDetail(posted=old), title="", description="", today=_TODAY)
    assert future_detail.posted is None
    assert old_detail.posted is None
    kept = check_facts(JobDetail(posted=recent), title="", description="", today=_TODAY)
    assert kept.posted is not None


def test_large_local_monthly_pay_survives_the_usd_band() -> None:
    rupiah = PayFact(
        value=Pay(
            minimum=Decimal("11000000"),
            maximum=Decimal("15000000"),
            currency="IDR",
            interval="monthly",
        ),
        confidence=1,
        evidence="11000000",
        parser_id="api:seek",
    )
    baht = PayFact(
        value=Pay(
            minimum=Decimal("100000"),
            maximum=Decimal("140000"),
            currency="THB",
            interval="monthly",
        ),
        confidence=1,
        evidence="140000",
        parser_id="api:seek",
    )
    kept_rupiah = check_facts(JobDetail(pay=rupiah), title="", description="", today=_TODAY)
    kept_baht = check_facts(JobDetail(pay=baht), title="", description="", today=_TODAY)
    assert kept_rupiah.pay is not None
    assert kept_baht.pay is not None


def test_unknown_role_and_country_are_dropped() -> None:
    detail = JobDetail(
        role=_text("astronaut", "astronaut"),
        locations=LocationFact(
            value=[Place(city="Austin", country="ZZ")],
            confidence=1,
            evidence="Austin",
            parser_id="default",
        ),
    )
    checked = check_facts(detail, title="astronaut", description="Austin", today=_TODAY)
    assert checked.role is None
    assert checked.locations is None

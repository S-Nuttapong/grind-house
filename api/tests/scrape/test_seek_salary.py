"""SEEK salary labels become a source pay fact."""

from decimal import Decimal

from jobhunt.scrape.sources.seek import SeekSource

_SOURCE = SeekSource()


def test_salary_label_is_an_api_pay_fact() -> None:
    single = _SOURCE.payload_facts({"country": "th", "salary": "฿40,000 per month"})
    assert single.locations is not None
    assert single.locations.value[0].country == "TH"
    assert single.pay is not None
    assert single.pay.parser_id == "api:seek"
    assert single.pay.value.minimum == Decimal("40000")
    assert single.pay.value.maximum is None
    assert single.pay.value.currency == "THB"
    assert single.pay.value.interval == "monthly"

    ranged = _SOURCE.payload_facts({"country": "TH", "salary": "฿55,000 – ฿80,000 per month"})
    assert ranged.pay is not None
    assert ranged.pay.value.minimum == Decimal("55000")
    assert ranged.pay.value.maximum == Decimal("80000")


def test_empty_salary_label_leaves_pay_empty() -> None:
    detail = _SOURCE.payload_facts({"country": "TH", "salary": ""})
    assert detail.pay is None
    assert detail.locations is not None

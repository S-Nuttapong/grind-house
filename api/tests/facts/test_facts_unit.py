"""Default parser, api extractors, and the decision rule. No database."""

from decimal import Decimal

import pytest
from jobhunt.facts.api_fields import from_payload
from jobhunt.facts.base import ParseHints
from jobhunt.facts.decide import ModeScore, choose_field
from jobhunt.facts.default import DefaultParser
from jobhunt.facts.places import resolve_places

_PARSER = DefaultParser()


def test_empty_text_is_empty() -> None:
    assert _PARSER.parse("").pay is None
    assert _PARSER.parse("   ").locations is None


def test_euro_range_and_not_revenue() -> None:
    text = "The base salary is €66,000 - €83,000 per year."
    pay = _PARSER.parse(text).pay
    assert pay is not None
    assert pay.value.currency == "EUR"
    assert pay.value.minimum == Decimal("66000")
    assert pay.value.maximum == Decimal("83000")
    assert pay.value.interval == "yearly"
    assert pay.evidence in text
    assert _PARSER.parse("Revenue of $50,000,000 last year.").pay is None


def test_cad_prefix_and_monthly_ringgit() -> None:
    cad = _PARSER.parse("Base salary: CA$135,200 - CA$202,800 per year.").pay
    assert cad is not None
    assert cad.value.currency == "CAD"
    assert cad.value.minimum == Decimal("135200")
    ringgit = _PARSER.parse("Salary: RM 4,000 – RM 6,000 per month.").pay
    assert ringgit is not None
    assert ringgit.value.currency == "MYR"
    assert ringgit.value.interval == "monthly"
    assert ringgit.value.minimum == Decimal("4000")


def test_hybrid_signature_is_not_a_workplace() -> None:
    text = "Familiarity with post-quantum cryptography and hybrid signature schemes."
    assert _PARSER.parse(text).workplace is None


def test_location_line_and_workplace_parenthetical() -> None:
    text = "### Available Locations: Austin, London, or Lisbon (Hybrid)"
    detail = _PARSER.parse(text)
    assert detail.workplace is not None
    assert detail.workplace.value == "hybrid"
    assert detail.locations is not None
    countries = {place.country for place in detail.locations.value}
    assert {"US", "GB", "PT"} <= countries
    assert detail.locations.evidence in text


def test_employment_line() -> None:
    text = "Employment type: Full-time"
    fact = _PARSER.parse(text).job_type
    assert fact is not None
    assert fact.value == "fulltime"
    assert fact.evidence in text


def test_wanted_limits_fields() -> None:
    text = "Employment type: Full-time\nSalary: €66,000 - €83,000 per year."
    detail = _PARSER.parse(text, ParseHints(wanted={"job_type"}))
    assert detail.job_type is not None
    assert detail.pay is None


@pytest.mark.parametrize(
    ("text", "country", "city"),
    [
        ("Austin, TX", "US", "Austin"),
        ("Seoul, South Korea", "KR", "Seoul"),
        ("Lisbon, Portugal", "PT", "Lisbon"),
    ],
)
def test_gazetteer(text: str, country: str, city: str) -> None:
    places = resolve_places(text)
    assert places
    assert places[0].country == country
    assert places[0].city == city


def test_distributed_resolves_nothing() -> None:
    assert resolve_places("Distributed") == []


def test_greenhouse_offices_and_placeholder() -> None:
    detail = from_payload(
        "greenhouse",
        {
            "location": {"name": "Hybrid"},
            "offices": [
                {"name": "Austin", "location": "Austin, TX, United States"},
                {"name": "Lisbon", "location": "Lisbon, Portugal"},
                {"name": "London", "location": "London, United Kingdom"},
            ],
        },
    )
    assert detail.workplace is not None
    assert detail.workplace.value == "hybrid"
    assert detail.locations is not None
    assert {place.country for place in detail.locations.value} >= {"US", "PT", "GB"}


def test_stripe_canada_office_name() -> None:
    detail = from_payload(
        "greenhouse",
        {"location": {"name": "N/A"}, "offices": [{"name": "Canada Locations", "location": None}]},
    )
    assert detail.locations is not None
    assert detail.locations.value[0].country == "CA"


def test_lever_salary_range() -> None:
    detail = from_payload(
        "lever",
        {
            "salaryRange": {
                "min": 1529960,
                "max": 1799950,
                "currency": "CZK",
                "interval": "per-year-salary",
            },
            "workplaceType": "hybrid",
            "categories": {"commitment": "Full-time", "allLocations": ["Prague"]},
        },
    )
    assert detail.pay is not None
    assert detail.pay.value.currency == "CZK"
    assert detail.pay.value.interval == "yearly"
    assert detail.pay.value.minimum == Decimal("1529960")
    assert detail.workplace is not None and detail.workplace.value == "hybrid"
    assert detail.job_type is not None and detail.job_type.value == "fulltime"
    assert detail.locations is not None
    assert detail.locations.value[0].country == "CZ"


def test_ashby_secondary_location() -> None:
    detail = from_payload(
        "ashby",
        {
            "location": "Remote",
            "secondaryLocations": [{"location": "Berlin, Germany"}],
            "employmentType": "FullTime",
            "compensation": {
                "summaryComponents": [
                    {
                        "compensationType": "Salary",
                        "minValue": 80000,
                        "maxValue": 100000,
                        "currencyCode": "EUR",
                        "interval": "1 YEAR",
                    }
                ]
            },
        },
    )
    assert detail.pay is not None
    assert detail.pay.value.currency == "EUR"
    assert detail.locations is not None
    assert "DE" in {place.country for place in detail.locations.value}


def test_seek_salary_is_not_an_api_fact() -> None:
    detail = from_payload("seek", {"salary": "RM 4,000 – RM 6,000 per month", "country": "MY"})
    assert detail.pay is None
    assert detail.locations is not None
    assert detail.locations.value[0].country == "MY"


def test_choose_highest_recall_above_precision_bar() -> None:
    choice = choose_field(
        [
            ModeScore("default", 0.98, 0.40, 0.01),
            ModeScore("gliner", 0.99, 0.20, 1.0),
            ModeScore("default+gliner", 0.97, 0.55, 1.0),
        ]
    )
    assert choice.mode == "default+gliner"
    assert choice.flagged is False


def test_choose_faster_when_recall_is_tied() -> None:
    choice = choose_field(
        [
            ModeScore("default", 0.98, 0.50, 0.01),
            ModeScore("gliner", 0.98, 0.505, 1.2),
        ]
    )
    assert choice.mode == "default"


def test_choose_flags_between_90_and_97() -> None:
    choice = choose_field(
        [ModeScore("default", 0.94, 0.3, 0.01), ModeScore("gliner", 0.91, 0.8, 1)]
    )
    assert choice.mode == "default"
    assert choice.flagged is True


def test_choose_source_only_below_90() -> None:
    choice = choose_field([ModeScore("default", 0.8, 0.9, 0.01)])
    assert choice.mode == "api"
    assert choice.flagged is False

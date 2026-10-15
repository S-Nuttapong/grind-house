"""Default parser, api extractors, and the decision rule. No database."""

from decimal import Decimal

import pytest
from jobhunt.facts.api_fields import from_payload
from jobhunt.facts.base import ParseHints, PostingInput
from jobhunt.facts.decide import ModeScore, choose_field
from jobhunt.facts.default import DefaultParser
from jobhunt.facts.experience import experience_from_text
from jobhunt.facts.pay import pay_from_label
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


def test_seek_salary_label_is_an_api_fact() -> None:
    detail = from_payload("seek", {"salary": "RM 4,000 – RM 6,000 per month", "country": "MY"})
    assert detail.pay is not None
    assert detail.pay.parser_id == "api:seek"
    assert detail.pay.value.currency == "MYR"
    assert detail.pay.value.minimum == Decimal("4000")
    assert detail.pay.value.maximum == Decimal("6000")
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


@pytest.mark.parametrize(
    ("label", "country", "low", "high", "currency", "interval"),
    [
        ("฿40,000 per month", "TH", "40000", None, "THB", "monthly"),
        ("฿55,000 – ฿80,000 per month", "TH", "55000", "80000", "THB", "monthly"),
        ("₱100,000 – ₱140,000 per month", "PH", "100000", "140000", "PHP", "monthly"),
        ("SGD 7500 - 10500 per month", "SG", "7500", "10500", "SGD", "monthly"),
        ("40-60k THB", "TH", "40000", "60000", "THB", "monthly"),
        ("$150-160K plus benefits", "AU", "150000", "160000", "AUD", "yearly"),
        ("$130,000+super", "AU", "130000", None, "AUD", "yearly"),
        ("From 150000 to 165000 NZD per year", "NZ", "150000", "165000", "NZD", "yearly"),
        ("Up to $170,000 + Super", "AU", None, "170000", "AUD", "yearly"),
        ("Up to 150K plus generous bonus", "TH", None, "150000", "THB", "monthly"),
        (
            "Rp\xa011.000.000 – Rp\xa015.000.000 per month",
            "ID",
            "11000000",
            "15000000",
            "IDR",
            "monthly",
        ),
        ("฿100,000 – ฿140,000 per month", "TH", "100000", "140000", "THB", "monthly"),
    ],
)
def test_pay_from_label(
    label: str,
    country: str,
    low: str | None,
    high: str | None,
    currency: str,
    interval: str,
) -> None:
    pay = pay_from_label(label, country)
    assert pay is not None
    assert pay.minimum == (None if low is None else Decimal(low))
    assert pay.maximum == (None if high is None else Decimal(high))
    assert pay.currency == currency
    assert pay.interval == interval


@pytest.mark.parametrize(
    "label",
    ["Competitive", "World Class Benefits", "0", "AUD 170 - 180 per annum", "RM 1,500 per month"],
)
def test_pay_from_label_drops_non_pay_and_implausible_amounts(label: str) -> None:
    assert pay_from_label(label, "MY") is None


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("5\\-8 years of hands-on experience", 5, 8),
        ("7\\+ years of frontend experience", 7, None),
        ("Minimum 3 years of relevant experience", 3, None),
        ("at least 5 years of software engineering experience", 5, None),
        ("2 to 4 years of professional software development experience", 2, 4),
        ("6–9 years of hands-on software design and development experience", 6, 9),
        ("**Experience:** Minimum 6 years", 6, None),
        ("5-8 Years Exp", 5, 8),
        ("(4–6 Years Experience)", 4, 6),
        ("7+ years of frontend experience, including at least 2 years in a lead role", 7, None),
        ("More than 3 year’s experiences in software development", 3, None),
    ],
)
def test_experience_from_text(text: str, low: int, high: int | None) -> None:
    fact = experience_from_text(text)
    assert fact is not None
    assert fact.value.minimum == low
    assert fact.value.maximum == high
    assert fact.evidence in text


@pytest.mark.parametrize(
    "text",
    [
        "nearly 70 years of history",
        "over 40 years of specialist insurance expertise",
        "2 year renewable contract",
        "Fixed-term (2 years)",
        "erased after 2 years of inactivity",
        "We need 5 years of experience",
    ],
)
def test_experience_ignores_company_history_and_contract_length(text: str) -> None:
    assert experience_from_text(text) is None


def test_title_experience_is_a_fact() -> None:
    detail = _PARSER.parse(
        PostingInput(title="Engineer (4–6 Years Experience)", description_md="Build things.")
    )
    assert detail.experience is not None
    assert detail.experience.value.minimum == 4
    assert detail.experience.value.maximum == 6

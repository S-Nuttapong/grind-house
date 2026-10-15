from decimal import Decimal

import pytest
from jobhunt.scrape.normalize.company import norm_company
from jobhunt.scrape.normalize.level import EXCLUDED_LEVELS, infer_level
from jobhunt.scrape.normalize.location import parse_location
from jobhunt.scrape.normalize.salary import normalize_salary
from jobhunt.scrape.normalize.text import content_hash, html_to_md
from jobhunt.scrape.normalize.title import norm_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme Inc.", "acme"),
        ("Acme, LLC", "acme"),
        ("Acme Pte. Ltd.", "acme"),
        ("Acme (Singapore)", "acme"),
        ("Société Générale SA", "societe generale"),
        ("Grab Holdings", "grab holdings"),
        ("  Foo   Bar  Corp ", "foo bar"),
        ("Sdn Bhd Example", "sdn bhd example"),
    ],
)
def test_norm_company(raw: str, expected: str) -> None:
    assert norm_company(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sr. SWE", "senior software engineer"),
        ("Jr Dev", "junior developer"),
        ("Front-End Eng", "frontend engineer"),
        ("Front End Engineer", "frontend engineer"),
        ("Back-end Engineer", "backend engineer"),
        ("Full Stack Engineer", "fullstack engineer"),
        ("Staff Engineer (Remote)", "staff engineer"),
        ("Staff Engineer - Singapore", "staff engineer"),
        ("Senior Engineer | Bangkok", "senior engineer"),
        ("Platform Engineer, Remote", "platform engineer"),
        ("  SWE,  Payments ", "software engineer payments"),
    ],
)
def test_norm_title(raw: str, expected: str) -> None:
    assert norm_title(raw) == expected


@pytest.mark.parametrize(
    ("title", "hint", "expected"),
    [
        ("Intern", None, "intern"),
        ("Junior Engineer", None, "junior"),
        ("Graduate Engineer", None, "junior"),
        ("Principal Engineer", None, "principal"),
        ("Staff Engineer", None, "staff"),
        ("Engineering Manager", None, "manager"),
        ("Head of Platform", None, "manager"),
        ("Tech Lead", None, "lead"),
        ("Senior Engineer", None, "senior"),
        ("Software Engineer", "Mid-Senior level", "senior"),
        ("Software Engineer", None, "unknown"),
        ("Senior Staff Engineer", None, "staff"),
    ],
)
def test_infer_level(title: str, hint: str | None, expected: str) -> None:
    assert infer_level(title, hint) == expected


def test_excluded_levels_are_manager_principal_junior_and_intern() -> None:
    assert EXCLUDED_LEVELS == frozenset({"manager", "principal", "junior", "intern"})


@pytest.mark.parametrize(
    ("raw", "hint", "country", "city", "remote", "tz"),
    [
        ("Bangkok, Thailand", None, "TH", "Bangkok", "unknown", (7, 7)),
        ("Singapore", None, "SG", "Singapore", "unknown", (8, 8)),
        ("London, UK", None, "GB", "London", "unknown", (0, 1)),
        ("Krung Thep", None, "TH", "Bangkok", "unknown", (None, None)),
        ("Chiang Mai", None, "TH", "Chiang Mai", "unknown", (None, None)),
        ("Phuket", None, "TH", "Phuket", "unknown", (None, None)),
        ("Taipei, Taiwan", None, "TW", "Taipei", "unknown", (8, 8)),
        ("Tokyo, Japan", None, "JP", "Tokyo", "unknown", (9, 9)),
        ("Sydney, Australia", None, "AU", "Sydney", "unknown", (8, 11)),
        ("Auckland, New Zealand", None, "NZ", "Auckland", "unknown", (12, 13)),
        ("Hong Kong", None, "HK", "Hong Kong", "unknown", (8, 8)),
        ("Kuala Lumpur, Malaysia", None, "MY", "Kuala Lumpur", "unknown", (8, 8)),
        ("Ho Chi Minh City, Vietnam", None, "VN", "Ho Chi Minh", "unknown", (7, 7)),
        ("Jakarta, Indonesia", None, "ID", "Jakarta", "unknown", (7, 9)),
        ("Berlin, Germany", None, "DE", "Berlin", "unknown", (1, 2)),
        ("Amsterdam, Netherlands", None, "NL", "Amsterdam", "unknown", (1, 2)),
        ("Paris, France", None, "FR", "Paris", "unknown", (1, 2)),
        ("Austin, TX", None, "US", None, "unknown", (None, None)),
        ("Remote", None, None, None, "remote", (None, None)),
        ("Work from home", None, None, None, "remote", (None, None)),
        ("Hybrid Singapore", None, "SG", "Singapore", "hybrid", (8, 8)),
        ("Remote UTC+7", None, None, None, "remote", (7, 7)),
        ("Remote APAC", None, None, None, "remote", (5, 10)),
        ("Somewhere", None, None, None, "unknown", (None, None)),
        (None, "WFH", None, None, "remote", (None, None)),
    ],
)
def test_parse_location(
    raw: str | None,
    hint: str | None,
    country: str | None,
    city: str | None,
    remote: str,
    tz: tuple[int | None, int | None],
) -> None:
    assert parse_location(raw, hint) == (country, city, remote, tz[0], tz[1])


@pytest.mark.parametrize(
    ("low", "high", "currency", "interval", "usd"),
    [
        (100000, 120000, "USD", "yearly", Decimal("100000")),
        (50, None, "USD", "hourly", Decimal("104000")),
        (1000, None, "USD", "monthly", Decimal("12000")),
        (1000, None, "USD", "weekly", Decimal("52000")),
        (400, None, "USD", "daily", Decimal("104000")),
        (80000, None, "SGD", "yearly", Decimal("62373")),
        (80000, None, None, "yearly", None),
        (None, None, "USD", "yearly", None),
        (10, None, "USD", "biweekly", None),
        (1, 2, "usd", "annual", Decimal("1")),
    ],
)
def test_normalize_salary(
    low: int | None,
    high: int | None,
    currency: str | None,
    interval: str,
    usd: Decimal | None,
) -> None:
    result = normalize_salary(low, high, currency, interval)
    assert result[4] == usd


def test_html_to_md_strips_script_and_collapses_blanks() -> None:
    html = "<h1>Role</h1><script>alert(1)</script><p>Build things.</p>"
    rendered = html_to_md(html)
    assert "alert" not in rendered
    assert "Role" in rendered
    assert "Build things" in rendered


def test_content_hash_changes_when_description_changes() -> None:
    first = content_hash("senior engineer", "one")
    second = content_hash("senior engineer", "two")
    assert first != second
    assert first == content_hash("senior engineer", "one")

"""API board mapping. Live calls stay behind ``-m live`` and skip without a key."""

import os
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from jobhunt.composition import COMPOSITION
from jobhunt.core.http import HttpClient
from jobhunt.scrape.sources.adzuna import map_job as map_adzuna
from jobhunt.scrape.sources.base import FetchContext, RunPartial, ScopeView
from jobhunt.scrape.sources.jooble import JoobleSource, parse_salary
from jobhunt.scrape.sources.mycareersfuture import MyCareersFutureSource
from jobhunt.scrape.sources.mycareersfuture import map_job as map_mcf
from jobhunt.scrape.sources.reed import map_job as map_reed

_CONFIG = Path(__file__).resolve().parents[2] / "config"


def test_seed_scopes_are_the_ats_boards() -> None:
    scopes = yaml.safe_load((_CONFIG / "scopes.seed.yaml").read_text())
    assert len(scopes) == 3
    assert {item["source_id"] for item in scopes} == {"greenhouse", "lever", "ashby"}


def test_markets_name_indeed_countries() -> None:
    markets = yaml.safe_load((_CONFIG / "markets.yaml").read_text())
    indeed = {
        entry["indeed"]["country_indeed"]
        for entry in markets.values()
        if isinstance(entry, dict) and "indeed" in entry
    }
    assert "Thailand" in indeed
    assert "India" in indeed
    assert "Philippines" in indeed
    assert "usa" not in {str(name).lower() for name in indeed}


def test_adzuna_maps_a_disclosed_salary_in_the_feed_currency() -> None:
    posting = map_adzuna(
        {
            "id": "1",
            "title": "Engineer",
            "redirect_url": "https://www.adzuna.co.uk/land/ad/1",
            "created": "2026-10-01T00:00:00Z",
            "description": "Build things",
            "salary_min": 50000,
            "salary_max": 60000,
            "salary_is_predicted": 0,
            "contract_time": "full_time",
            "company": {"display_name": "Acme"},
            "location": {"display_name": "London"},
            "category": {"label": "IT Jobs"},
        },
        "United Kingdom",
        "GBP",
    )
    assert posting is not None
    assert posting.location_raw == "London, United Kingdom"
    assert posting.salary_min == 50000
    assert posting.salary_currency == "GBP"
    assert posting.salary_interval_raw == "yearly"
    assert posting.posted_at == date(2026, 10, 1)


def test_adzuna_drops_a_predicted_salary() -> None:
    posting = map_adzuna(
        {
            "id": "2",
            "title": "Engineer",
            "redirect_url": "https://www.adzuna.co.uk/land/ad/2",
            "salary_min": 40000,
            "salary_is_predicted": 1,
            "company": {"display_name": "Acme"},
            "location": {"display_name": "London, United Kingdom"},
        },
        "United Kingdom",
        "GBP",
    )
    assert posting is not None
    assert posting.salary_min is None
    assert posting.location_raw == "London, United Kingdom"


def test_reed_maps_day_first_dates_and_annual_pay() -> None:
    posting = map_reed(
        {
            "jobId": 42,
            "jobTitle": "Engineer",
            "jobUrl": "https://www.reed.co.uk/jobs/engineer/42",
            "employerName": "Acme",
            "locationName": "London",
            "minimumSalary": 40000,
            "maximumSalary": 50000,
            "date": "11/10/2026",
            "jobDescription": "Build things",
        }
    )
    assert posting is not None
    assert posting.posted_at == date(2026, 10, 11)
    assert posting.location_raw == "London, United Kingdom"
    assert posting.salary_currency == "GBP"
    assert posting.salary_interval_raw == "yearly"


def test_jooble_salary_string() -> None:
    assert parse_salary("17,600 - 20,000 UAH") == (17600, 20000, "UAH")
    assert parse_salary("17,600 UAH") == (17600, None, "UAH")
    assert parse_salary("") == (None, None, None)


def test_jooble_omits_the_api_key_from_a_partial_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOOBLE_API_KEYS", '{"TH": "super-secret-key"}')

    @respx.mock
    def run() -> None:
        respx.post("https://th.jooble.org/api/super-secret-key").mock(
            return_value=httpx.Response(400, text="no")
        )
        adapter = JoobleSource()
        scope = ScopeView(
            id=1,
            source_id="jooble",
            params={"search_term": "software engineer", "location": "Bangkok", "country": "TH"},
        )
        http = HttpClient(sleep=lambda _seconds: None, uniform=lambda _a, _b: 0)
        ctx = FetchContext(http=http, companies=[])
        with pytest.raises(RunPartial, match="HTTP 400") as caught:
            list(adapter.fetch(scope, ctx))
        assert "super-secret-key" not in str(caught.value)

    run()


def test_mycareersfuture_maps_monthly_sgd_and_skips_a_hidden_employer() -> None:
    posting = map_mcf(
        {
            "uuid": "abc",
            "title": "Software Engineer",
            "postedCompany": {"name": "Example Pte Ltd"},
            "metadata": {
                "jobPostId": "MCF-1",
                "jobDetailsUrl": "https://www.mycareersfuture.gov.sg/job/example",
                "newPostingDate": "2026-10-09",
                "isHideSalary": False,
                "isHideHiringEmployerName": False,
            },
            "address": {"isOverseas": False, "districts": [{"location": "D14 Geylang, Eunos"}]},
            "salary": {"minimum": 4000, "maximum": 6000, "type": {"salaryType": "Monthly"}},
            "employmentTypes": [
                {"employmentType": "Contract"},
                {"employmentType": "Full Time"},
            ],
            "positionLevels": [{"position": "Senior"}],
            "flexibleWorkArrangements": [{"flexibleWorkArrangement": "Telecommuting"}],
        }
    )
    assert posting is not None
    assert posting.company_name == "Example Pte Ltd"
    assert posting.location_raw == "D14 Geylang, Eunos, Singapore"
    assert posting.salary_interval_raw == "monthly"
    assert posting.salary_currency == "SGD"
    assert posting.employment_type_raw == "Full Time"
    assert posting.remote_hint == "remote"
    assert (
        map_mcf(
            {
                "title": "Hidden",
                "uuid": "x",
                "metadata": {
                    "isHideHiringEmployerName": True,
                    "jobDetailsUrl": "https://example.com",
                },
                "postedCompany": {"name": "Secret"},
            }
        )
        is None
    )


def test_registry_serves_the_new_boards() -> None:
    for source_id in ("naukri", "adzuna", "reed", "jooble", "mycareersfuture"):
        assert COMPOSITION.source(source_id).id == source_id


def test_adzuna_refuses_thailand() -> None:
    scope = ScopeView(
        id=1,
        source_id="adzuna",
        params={"search_term": "software engineer", "country": "th"},
    )
    ctx = FetchContext(http=HttpClient(), companies=[])
    with pytest.raises(RunPartial, match="not an Adzuna feed"):
        list(COMPOSITION.source("adzuna").fetch(scope, ctx))


@pytest.mark.live
def test_mycareersfuture_sg_smoke() -> None:
    scope = ScopeView(
        id=1,
        source_id="mycareersfuture",
        params={"search_term": "software engineer", "results_wanted": 2},
    )
    ctx = FetchContext(http=HttpClient(), companies=[])
    batches = list(MyCareersFutureSource().fetch(scope, ctx))
    assert batches[0].postings


@pytest.mark.live
def test_adzuna_gb_smoke() -> None:
    if not os.environ.get("ADZUNA_APP_ID") or not os.environ.get("ADZUNA_APP_KEY"):
        pytest.skip("Adzuna keys are not set")
    scope = ScopeView(
        id=1,
        source_id="adzuna",
        params={
            "search_term": "software engineer",
            "country": "gb",
            "location": "London",
            "results_wanted": 2,
        },
    )
    ctx = FetchContext(http=HttpClient(), companies=[])
    batches = list(COMPOSITION.source("adzuna").fetch(scope, ctx))
    assert batches[0].postings


@pytest.mark.live
def test_reed_uk_smoke() -> None:
    if not os.environ.get("REED_API_KEY"):
        pytest.skip("REED_API_KEY is not set")
    scope = ScopeView(
        id=1,
        source_id="reed",
        params={"search_term": "software engineer", "location": "London", "results_wanted": 2},
    )
    ctx = FetchContext(http=HttpClient(), companies=[])
    batches = list(COMPOSITION.source("reed").fetch(scope, ctx))
    assert batches[0].postings


@pytest.mark.live
def test_jooble_th_smoke() -> None:
    if not os.environ.get("JOOBLE_API_KEYS"):
        pytest.skip("JOOBLE_API_KEYS is not set")
    scope = ScopeView(
        id=1,
        source_id="jooble",
        params={
            "search_term": "software engineer",
            "location": "Bangkok",
            "country": "TH",
            "results_wanted": 2,
        },
    )
    ctx = FetchContext(http=HttpClient(), companies=[])
    batches = list(COMPOSITION.source("jooble").fetch(scope, ctx))
    assert batches[0].postings

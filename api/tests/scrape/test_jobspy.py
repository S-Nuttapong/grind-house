"""JobSpy row mapping. Live fetches stay behind ``-m live``."""

import json
from pathlib import Path

import pytest
from jobhunt.scrape.sources.jobspy_src import _cap, _scrape_call, map_row

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "jobspy" / "indeed_rows.json"


def test_indeed_rows_map_title_company_and_url() -> None:
    rows = json.loads(FIXTURE.read_text())
    postings = [mapped for row in rows if (mapped := map_row("indeed", row)) is not None]
    assert len(postings) == len(rows)
    ready = [
        posting
        for posting in postings
        if posting.title and posting.company_name and posting.source_url and posting.location_raw
    ]
    assert len(ready) / len(postings) >= 0.95
    assert postings[0].apply_url == "https://example.com/apply/1"
    assert postings[0].company_hint["company_url"] == "https://example.com"
    assert postings[1].remote_hint == "remote"
    assert postings[1].source_job_id
    assert postings[1].level_hint == "Mid-Senior level"


def test_jobspy_maps_function_and_industry() -> None:
    posting = map_row(
        "indeed",
        {
            "title": "Engineer",
            "job_url": "https://example.com/jobs/1",
            "company": "Acme",
            "job_function": "Engineering",
            "company_industry": "Financial Services",
        },
    )
    assert posting is not None
    assert posting.role_hint == "Engineering"
    assert posting.industry_hint == "Financial Services"


def test_linkedin_results_are_capped() -> None:
    assert _cap("linkedin_guest", 500) == 100
    assert _cap("indeed", 500) == 200
    assert _cap("indeed", 20) == 20
    assert _cap("naukri", 500) == 50


def test_indeed_scope_must_name_its_country() -> None:
    with pytest.raises(ValueError, match="country_indeed"):
        _scrape_call("indeed", {"search_term": "software engineer"}, 5)


def test_indeed_country_is_not_defaulted_to_usa() -> None:
    call = _scrape_call(
        "indeed",
        {"search_term": "software engineer", "country_indeed": "Thailand", "location": "Thailand"},
        5,
    )
    assert call["country_indeed"] == "Thailand"
    assert "usa" not in call.values()


def test_linkedin_omits_country_when_the_scope_has_none() -> None:
    call = _scrape_call("linkedin_guest", {"search_term": "frontend engineer"}, 5)
    assert "country_indeed" not in call


@pytest.mark.live
def test_indeed_sg_smoke() -> None:
    from jobhunt.scrape.sources.jobspy_src import _scrape

    rows = _scrape(
        "indeed",
        {
            "search_term": "software engineer",
            "location": "Singapore",
            "country_indeed": "Singapore",
            "hours_old": 72,
        },
        5,
    )
    assert rows
    assert map_row("indeed", rows[0]) is not None


@pytest.mark.live
def test_indeed_th_smoke() -> None:
    from jobhunt.scrape.sources.jobspy_src import _scrape

    rows = _scrape(
        "indeed",
        {
            "search_term": "software engineer",
            "location": "Thailand",
            "country_indeed": "Thailand",
            "hours_old": 72,
        },
        5,
    )
    assert rows
    assert map_row("indeed", rows[0]) is not None


@pytest.mark.live
def test_indeed_uk_smoke() -> None:
    from jobhunt.scrape.sources.jobspy_src import _scrape

    rows = _scrape(
        "indeed",
        {
            "search_term": "software engineer",
            "location": "London",
            "country_indeed": "UK",
            "hours_old": 72,
        },
        5,
    )
    assert rows
    assert map_row("indeed", rows[0]) is not None


@pytest.mark.live
def test_naukri_bengaluru_smoke() -> None:
    from jobhunt.scrape.sources.jobspy_src import _scrape

    rows = _scrape(
        "naukri",
        {"search_term": "software engineer", "location": "Bengaluru", "hours_old": 72},
        5,
    )
    assert rows
    assert map_row("naukri", rows[0]) is not None

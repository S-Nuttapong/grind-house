"""JobSpy row mapping. Live fetches stay behind ``-m live``."""

import json
from pathlib import Path

import pytest
from jobhunt.sources.jobspy_src import _cap, map_row

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "jobspy" / "indeed_rows.json"


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


def test_linkedin_results_are_capped() -> None:
    assert _cap("linkedin_guest", 500) == 100
    assert _cap("indeed", 500) == 200
    assert _cap("indeed", 20) == 20


@pytest.mark.live
def test_indeed_sg_smoke() -> None:
    from jobhunt.sources.jobspy_src import _scrape

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

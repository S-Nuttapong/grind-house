"""ATS mappings are checked against saved public-board responses."""

import json
from pathlib import Path

from jobhunt.scrape.sources.ashby import map_job as map_ashby
from jobhunt.scrape.sources.base import RawPosting
from jobhunt.scrape.sources.greenhouse import map_job as map_greenhouse
from jobhunt.scrape.sources.lever import map_job as map_lever

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ats"


def _coverage(postings: list[RawPosting]) -> float:
    if not postings:
        return 0.0
    ready = 0
    for posting in postings:
        if posting.title and posting.company_name and posting.source_url and posting.location_raw:
            ready += 1
    return ready / len(postings)


def test_greenhouse_fixture_maps_public_jobs() -> None:
    payload = json.loads((FIXTURES / "greenhouse_gitlab.json").read_text())
    postings = [
        mapped
        for item in payload["jobs"]
        if (mapped := map_greenhouse(item, "GitLab", "gitlab")) is not None
    ]
    assert len(postings) == len(payload["jobs"])
    assert _coverage(postings) >= 0.95
    assert postings[0].source_id == "greenhouse"
    assert postings[0].apply_url == postings[0].source_url
    assert postings[0].company_hint["slug"] == "gitlab"
    assert postings[0].posted_at is not None


def test_greenhouse_unescapes_content() -> None:
    posting = map_greenhouse(
        {
            "id": 1,
            "title": "Engineer",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            "location": {"name": "Singapore"},
            "content": "&lt;p&gt;R&amp;D&lt;/p&gt;",
        },
        "Acme",
        "acme",
    )
    assert posting is not None
    assert posting.description_html == "<p>R&D</p>"


def test_lever_fixture_maps_public_jobs() -> None:
    payload = json.loads((FIXTURES / "lever_spotify.json").read_text())
    postings = [
        mapped for item in payload if (mapped := map_lever(item, "Spotify", "spotify")) is not None
    ]
    assert len(postings) == len(payload)
    assert _coverage(postings) >= 0.95
    assert postings[0].source_id == "lever"
    assert postings[0].description_html
    assert postings[0].posted_at is not None


def test_ashby_fixture_maps_public_job() -> None:
    payload = json.loads((FIXTURES / "ashby_ashby.json").read_text())
    postings = [
        mapped
        for item in payload["jobs"]
        if (mapped := map_ashby(item, "Ashby", "ashby")) is not None
    ]
    assert len(postings) == len(payload["jobs"])
    assert _coverage(postings) >= 0.95
    assert postings[0].remote_hint == "Remote"
    assert postings[0].salary_currency == "EUR"
    assert postings[0].salary_min == 110000
    assert postings[0].salary_interval_raw == "yearly"
    assert postings[0].employment_type_raw == "FullTime"

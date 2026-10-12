"""Searches, pacing, hooks, and the tick."""

import ssl
from collections.abc import Iterator
from pathlib import Path

import httpx
import psycopg
import pytest
import respx
from fastapi.testclient import TestClient
from jobhunt.app import create_app
from jobhunt.core.db import advisory_lock, close_pool
from jobhunt.core.http import HttpClient
from jobhunt.scrape import repo
from jobhunt.scrape.ats import detect_ats, follow_apply
from jobhunt.scrape.hooks import HookOutcome, run_phase
from jobhunt.scrape.searches import expand, or_query
from jobhunt.scrape.sources.base import FetchContext, RunPartial, ScopeView
from jobhunt.scrape.sources.linkedin import parse_cards
from jobhunt.scrape.sources.pacing import Breaker, empty_is_throttle
from jobhunt.scrape.sources.registry import adapter_for
from jobhunt.scrape.sources.seek import map_job
from jobhunt.scrape.tick import tick

_CARD = """
<div data-entity-urn="urn:li:jobPosting:42">
  <h3 class="base-search-card__title">Software Engineer</h3>
  <h4 class="base-search-card__subtitle">Acme</h4>
  <span class="job-search-card__location">Bangkok, Thailand</span>
  <time datetime="2026-10-01"></time>
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/42"></a>
</div>
"""


def test_or_query_quotes_phrases() -> None:
    assert or_query(["Software Engineer", "frontend"]) == '"Software Engineer" OR frontend'


def test_expand_skips_boards_without_a_market() -> None:
    found = expand(
        {
            "keywords": ["Software Engineer", "frontend"],
            "countries": ["TH", "SG"],
            "sources": ["linkedin_guest", "glassdoor"],
        }
    )
    countries = {(source, country) for source, country, _params in found}
    assert ("linkedin_guest", "TH") in countries
    assert ("glassdoor", "TH") not in countries
    assert ("glassdoor", "SG") in countries
    linkedin = next(params for source, country, params in found if source == "linkedin_guest")
    assert linkedin["search_term"] == '"Software Engineer" OR frontend'
    assert linkedin["geo_id"]


def test_breaker_opens_on_two_signals_and_resets_when_clean() -> None:
    breaker = Breaker()
    breaker.note_throttle()
    assert not breaker.opened
    again = Breaker(prior=1)
    again.note_throttle()
    assert again.pause_minutes == 30
    breaker.note_throttle()
    assert breaker.pause_minutes == 30
    repeat = Breaker(prior=breaker.stored())
    repeat.note_throttle()
    repeat.note_throttle()
    assert repeat.pause_minutes == 120
    clean = Breaker(prior=2)
    clean.note_clean()
    assert clean.stored() == 0


def test_empty_page_without_a_no_jobs_message_is_a_throttle() -> None:
    assert empty_is_throttle("", 0)
    assert not empty_is_throttle("No matching jobs", 0)
    assert not empty_is_throttle("x" * 20_000, 0)
    assert not empty_is_throttle("", 3)


def test_linkedin_card_and_authwall() -> None:
    cards = parse_cards(_CARD, "TH")
    assert cards[0].source_job_id == "42"
    assert cards[0].company_name == "Acme"
    with pytest.raises(RunPartial, match="login or captcha"):
        parse_cards("<html>please login authwall</html>", "TH")


def test_seek_maps_a_search_row() -> None:
    posting = map_job(
        "th.jobsdb.com",
        "TH",
        {
            "id": "900",
            "title": "Software Engineer",
            "advertiser": {"description": "Acme"},
            "locations": [{"label": "Bangkok"}],
            "listingDate": "2026-10-01T00:00:00Z",
            "teaser": "Build software",
            "classifications": [{"subclassification": {"description": "Developers/Programmers"}}],
            "workArrangements": {"data": [{"label": {"text": "Hybrid"}}]},
            "salaryLabel": "THB 80000",
        },
    )
    assert posting is not None
    assert posting.source_url == "https://th.jobsdb.com/job/900"
    assert posting.remote_hint == "Hybrid"
    indonesia = map_job(
        "id.jobstreet.com",
        "ID",
        {"id": "1", "title": "Engineer", "advertiser": {"description": "Acme"}},
    )
    assert indonesia is not None
    assert "/id/job/1" in indonesia.source_url


def test_linkedin_retries_an_empty_page(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    with respx.mock:
        respx.get(url__regex=r".*seeMoreJobPostings.*").mock(
            side_effect=[httpx.Response(200, text=""), httpx.Response(200, text=_CARD)]
        )
        http = HttpClient(
            httpx.Client(),
            sleep=lambda seconds: slept.append(seconds),
            min_delay=6,
            max_delay=6,
        )
        batches = list(
            adapter_for("linkedin_guest").fetch(
                ScopeView(
                    id=0,
                    source_id="linkedin_guest",
                    params={
                        "geo_id": "1",
                        "search_term": "software",
                        "country": "TH",
                        "max_pages": 1,
                    },
                ),
                FetchContext(http=http, companies=[]),
            )
        )
    assert 45 in slept
    assert batches[0].postings[0].title == "Software Engineer"
    _ = monkeypatch


def test_self_signed_certificate_is_a_corporate_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from jobhunt.scrape.network import corporate_network

    monkeypatch.delenv("JOBHUNT_ALLOW_CORP_NETWORK", raising=False)

    class _Rejected:
        def __enter__(self) -> object:
            raise ssl.SSLCertVerificationError("self signed")

        def __exit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(
        "jobhunt.scrape.network.socket.create_connection",
        lambda *args, **kwargs: _Rejected(),
    )
    assert corporate_network()
    monkeypatch.setenv("JOBHUNT_ALLOW_CORP_NETWORK", "1")
    assert not corporate_network()


def test_hooks_skip_and_still_run_after(tmp_path: Path, database_url: str) -> None:
    config = tmp_path / "scrape.yaml"
    config.write_text(
        """
tick:
  before_start:
    - name: stop
      run: /usr/bin/false
      timeout: 5s
      on_fail: skip_tick
  after:
    - name: restore
      run: /usr/bin/true
      timeout: 5s
""",
        encoding="utf-8",
    )
    try:
        assert run_phase("before_start", config=config).skip
        run_phase("after", config=config)
        with psycopg.connect(database_url) as conn:
            rows = conn.execute("SELECT name FROM tick_hooks ORDER BY id").fetchall()
        assert [row[0] for row in rows] == ["stop", "restore"]
    finally:
        with psycopg.connect(database_url) as conn:
            conn.execute("DELETE FROM tick_hooks")
            conn.commit()


def test_hook_runner_does_not_use_a_shell(tmp_path: Path, database_url: str) -> None:
    marker = tmp_path / "created-by-shell"
    config = tmp_path / "scrape.yaml"
    config.write_text(
        f"""
tick:
  before_start:
    - name: literal
      run: "/bin/echo hello > {marker}"
      timeout: 5s
""",
        encoding="utf-8",
    )
    try:
        run_phase("before_start", config=config)
        assert not marker.exists()
    finally:
        with psycopg.connect(database_url) as conn:
            conn.execute("DELETE FROM tick_hooks")
            conn.commit()


def test_after_runs_when_scraping_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phases: list[str] = []

    def record(phase: str) -> HookOutcome:
        phases.append(phase)
        return HookOutcome()

    monkeypatch.setattr("jobhunt.scrape.tick.run_phase", record)
    monkeypatch.setattr("jobhunt.scrape.tick.vpn_state_path", lambda: tmp_path / "absent")
    monkeypatch.setattr("jobhunt.scrape.tick.corporate_network", lambda: False)

    def boom(_search_id: int | None) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr("jobhunt.scrape.tick._work", boom)
    with pytest.raises(RuntimeError, match="boom"):
        tick()
    assert phases == ["before_start", "after"]


def test_leftover_vpn_state_restores_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = tmp_path / "vpn.state"
    state.write_text("connected", encoding="utf-8")
    phases: list[str] = []
    monkeypatch.setattr("jobhunt.scrape.tick.vpn_state_path", lambda: state)
    monkeypatch.setattr(
        "jobhunt.scrape.tick.run_phase",
        lambda phase: phases.append(phase) or HookOutcome(),
    )
    monkeypatch.setattr("jobhunt.scrape.tick.corporate_network", lambda: False)
    monkeypatch.setattr("jobhunt.scrape.tick._work", lambda _search_id: 0)
    assert tick() == 0
    assert phases == ["after", "before_start", "after"]


def test_corporate_network_skips_the_tick(
    committed: psycopg.Connection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("jobhunt.scrape.tick.vpn_state_path", lambda: tmp_path / "absent")
    monkeypatch.setattr("jobhunt.scrape.tick.run_phase", lambda _phase: HookOutcome())
    monkeypatch.setattr("jobhunt.scrape.tick.corporate_network", lambda: True)
    assert tick() == 0
    rows = committed.execute("SELECT status, error FROM runs").fetchall()
    assert rows
    assert {row[0] for row in rows} == {"skipped"}
    assert "corporate network" in rows[0][1]


def test_tick_polls_two_searches_and_advances_ats(
    committed: psycopg.Connection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from jobhunt.scrape.sources.base import FetchBatch, RawPosting

    class _Fake:
        kind = "aggregator"
        full_board = False

        def __init__(self, source_id: str) -> None:
            self.id = source_id

        def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
            _ = ctx
            country = str(scope.params.get("country") or "TH")
            yield FetchBatch(
                postings=[
                    RawPosting(
                        source_id=self.id,
                        source_job_id=f"{self.id}-{country}",
                        source_url=f"https://example.test/{self.id}/{country}",
                        company_name=f"Tick Co {self.id}",
                        title="Software Engineer",
                        description_html="<p>Build software.</p>",
                        payload={"country": country},
                    )
                ]
            )

    monkeypatch.setattr("jobhunt.scrape.tick.vpn_state_path", lambda: tmp_path / "absent")
    monkeypatch.setattr("jobhunt.scrape.tick.run_phase", lambda _phase: HookOutcome())
    monkeypatch.setattr("jobhunt.scrape.tick.corporate_network", lambda: False)
    monkeypatch.setattr("jobhunt.scrape.tick.adapter_for", lambda source_id: _Fake(source_id))
    monkeypatch.setattr("jobhunt.scrape.tick.drain_details", lambda *_args, **_kwargs: None)
    committed.execute("UPDATE searches SET enabled = false")
    scope = committed.execute(
        """
        INSERT INTO fetch_scopes (name, source_id, params, cron, timezone)
        VALUES ('Tick greenhouse', 'greenhouse', '{}'::jsonb, '0 7 * * *', 'Asia/Bangkok')
        RETURNING id
        """
    ).fetchone()
    assert scope is not None
    scope_id = int(scope[0])
    ids: list[int] = []
    for name in ("Tick test A", "Tick test B"):
        row = committed.execute(
            """
            INSERT INTO searches (name, keywords, countries)
            VALUES (%s, ARRAY['Software Engineer'], ARRAY['TH'])
            RETURNING id
            """,
            (name,),
        ).fetchone()
        assert row is not None
        ids.append(int(row[0]))
        committed.execute(
            """
            INSERT INTO search_sources (search_id, source_id, poll_minutes)
            VALUES (%s, 'linkedin_guest', 30)
            """,
            (row[0],),
        )
    committed.commit()
    try:
        assert tick() >= 1
        runs = committed.execute(
            "SELECT status, new_jobs FROM runs WHERE search_id = ANY(%s) ORDER BY id",
            (ids,),
        ).fetchall()
        assert len(runs) == 2
        assert sum(int(row[1]) for row in runs) == 1
        polled = committed.execute(
            """
            SELECT count(*) FROM search_markets
            WHERE last_polled_at IS NOT NULL AND search_id = ANY(%s)
            """,
            (ids,),
        ).fetchone()
        assert polled == (2,)
        advanced = committed.execute(
            "SELECT next_run_at FROM fetch_scopes WHERE id = %s",
            (scope_id,),
        ).fetchone()
        assert advanced is not None and advanced[0] is not None
    finally:
        committed.execute("DELETE FROM fetch_scopes WHERE id = %s", (scope_id,))
        committed.execute("DELETE FROM searches WHERE id = ANY(%s)", (ids,))
        committed.execute("UPDATE searches SET enabled = true WHERE name = 'Software roles'")
        committed.execute("UPDATE fetch_scopes SET next_run_at = NULL")
        committed.commit()


def test_concurrent_tick_exits_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jobhunt.scrape.tick.run_phase", lambda _phase: HookOutcome())
    with advisory_lock("jobhunt.tick") as held:
        assert held
        assert tick() == 0


def test_apply_link_joins_the_ats_scope(conn: psycopg.Connection) -> None:
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/1") == ("greenhouse", "acme")
    assert detect_ats("https://jobs.workable.com/acme") is None
    company_id = repo.insert_company(conn, name="Acme Follow", name_norm="acme-follow")
    assert follow_apply(conn, company_id, "https://jobs.workable.com/acme/j/1") == "workable.com"
    assert follow_apply(conn, company_id, "https://boards.greenhouse.io/acme/jobs/9") is None
    company = conn.execute(
        "SELECT ats, ats_slug FROM companies WHERE id = %s",
        (company_id,),
    ).fetchone()
    assert company == ("greenhouse", "acme")
    scope = conn.execute(
        "SELECT params FROM fetch_scopes WHERE name = 'Discovered greenhouse'"
    ).fetchone()
    assert scope is not None
    assert company_id in scope[0]["company_ids"]


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    close_pool()
    with TestClient(create_app()) as test_client:
        yield test_client
    close_pool()
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM searches WHERE name = 'API test'")
        conn.commit()


def test_search_api_rejects_a_poll_under_the_source_floor(client: TestClient) -> None:
    created = client.post(
        "/api/searches",
        json={
            "name": "API test",
            "keywords": ["Software Engineer"],
            "countries": ["TH"],
            "timezone": "Asia/Bangkok",
            "sources": [{"source_id": "linkedin_guest", "poll_minutes": 30, "enabled": True}],
        },
    )
    assert created.status_code == 201
    listed = client.get("/api/searches")
    assert any(row["name"] == "API test" for row in listed.json())
    too_fast = client.post(
        "/api/searches",
        json={
            "name": "API test fast",
            "keywords": ["Software Engineer"],
            "countries": ["GB"],
            "timezone": "Not/AZone",
            "sources": [{"source_id": "adzuna", "poll_minutes": 30}],
        },
    )
    assert too_fast.status_code == 422
    assert "timezone" in too_fast.json()["detail"] or "minimum" in too_fast.json()["detail"]
    client.delete(f"/api/searches/{created.json()['id']}")

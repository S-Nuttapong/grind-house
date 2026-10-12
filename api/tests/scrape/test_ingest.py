"""Ingest acceptance: dedupe, ATS apply link, close, and edited descriptions."""

from jobhunt.scrape import repo
from jobhunt.scrape.ingest import ingest_batch
from jobhunt.scrape.sources.base import FetchBatch, RawPosting


def _company(conn) -> int:
    return repo.insert_company(
        conn,
        name="GitLab",
        name_norm="gitlab",
        tier="A",
        ats="greenhouse",
        ats_slug="gitlab",
    )


def _run(conn, source_id: str = "greenhouse") -> int:
    return repo.start_run(conn, source_id=source_id, scraper_version="test")


def _posting(**overrides: object) -> RawPosting:
    fields: dict[str, object] = {
        "source_id": "greenhouse",
        "source_job_id": "1",
        "source_url": "https://boards.greenhouse.io/gitlab/jobs/1",
        "apply_url": "https://boards.greenhouse.io/gitlab/jobs/1",
        "company_name": "GitLab",
        "title": "Senior Frontend Engineer",
        "location_raw": "Singapore",
        "description_html": "<p>Build the product.</p>",
        "payload": {"id": "1"},
    }
    fields.update(overrides)
    return RawPosting.model_validate(fields)


def test_job_function_sets_role_and_industry(conn) -> None:
    company_id = _company(conn)
    ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="greenhouse",
        batch=FetchBatch(
            company_id=company_id,
            postings=[
                _posting(
                    title="Engineer",
                    role_hint="Frontend",
                    industry_hint="Fintech",
                )
            ],
        ),
        full_board=True,
        similarity=0.85,
    )
    row = conn.execute(
        "SELECT role, industry FROM jobs WHERE company_id = %s",
        (company_id,),
    ).fetchone()
    assert row == ("frontend", "fintech")


def test_second_run_adds_no_jobs(conn) -> None:
    company_id = _company(conn)
    first = _run(conn)
    batch = FetchBatch(company_id=company_id, postings=[_posting()])
    fetched, new_jobs, _, _, _ = ingest_batch(
        conn, run_id=first, source_id="greenhouse", batch=batch, full_board=True, similarity=0.85
    )
    assert (fetched, new_jobs) == (1, 1)
    second = _run(conn)
    _, new_again, updated, closed, _ = ingest_batch(
        conn, run_id=second, source_id="greenhouse", batch=batch, full_board=True, similarity=0.85
    )
    assert (new_again, updated, closed) == (0, 0, 0)


def test_ats_posting_replaces_aggregator_apply_url(conn) -> None:
    company_id = _company(conn)
    linkedin = FetchBatch(
        postings=[
            _posting(
                source_id="linkedin_guest",
                source_job_id="li-1",
                source_url="https://www.linkedin.com/jobs/view/1",
                apply_url="https://www.linkedin.com/jobs/view/1",
                description_html=None,
                description_text="Build the product.",
                payload={"id": "li-1"},
            )
        ]
    )
    ingest_batch(
        conn,
        run_id=_run(conn, "linkedin_guest"),
        source_id="linkedin_guest",
        batch=linkedin,
        full_board=False,
        similarity=0.85,
    )
    ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="greenhouse",
        batch=FetchBatch(company_id=company_id, postings=[_posting()]),
        full_board=True,
        similarity=0.85,
    )
    jobs = conn.execute("SELECT id, apply_url FROM jobs").fetchall()
    postings = conn.execute("SELECT source_id FROM postings ORDER BY source_id").fetchall()
    assert len(jobs) == 1
    assert jobs[0][1] == "https://boards.greenhouse.io/gitlab/jobs/1"
    assert [row[0] for row in postings] == ["greenhouse", "linkedin_guest"]


def test_missing_posting_closes_the_job(conn) -> None:
    company_id = _company(conn)
    kept = _posting()
    dropped = _posting(
        source_job_id="2",
        source_url="https://boards.greenhouse.io/gitlab/jobs/2",
        apply_url="https://boards.greenhouse.io/gitlab/jobs/2",
        title="Backend Engineer",
        payload={"id": "2"},
    )
    ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="greenhouse",
        batch=FetchBatch(company_id=company_id, postings=[kept, dropped]),
        full_board=True,
        similarity=0.85,
    )
    _, _, _, closed, _ = ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="greenhouse",
        batch=FetchBatch(company_id=company_id, postings=[kept]),
        full_board=True,
        similarity=0.85,
    )
    assert closed == 1
    rows = conn.execute("SELECT title, closed_at IS NOT NULL FROM jobs ORDER BY title").fetchall()
    assert rows == [("Backend Engineer", True), ("Senior Frontend Engineer", False)]


def test_failed_fetch_does_not_close_jobs(conn) -> None:
    company_id = _company(conn)
    ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="greenhouse",
        batch=FetchBatch(company_id=company_id, postings=[_posting()]),
        full_board=True,
        similarity=0.85,
    )
    fetched, _, _, closed, _ = ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="greenhouse",
        batch=FetchBatch(company_id=company_id, failed=True),
        full_board=True,
        similarity=0.85,
    )
    assert (fetched, closed) == (0, 0)
    closed_at = conn.execute("SELECT closed_at FROM jobs").fetchone()
    assert closed_at is not None
    assert closed_at[0] is None


def test_edited_description_stores_a_new_payload(conn) -> None:
    company_id = _company(conn)
    original = _posting()
    ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="greenhouse",
        batch=FetchBatch(company_id=company_id, postings=[original]),
        full_board=True,
        similarity=0.85,
    )
    edited = _posting(
        description_html="<p>Build the product. Now with payments.</p>",
        payload={"id": "1b"},
    )
    _, _, updated, _, _ = ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="greenhouse",
        batch=FetchBatch(company_id=company_id, postings=[edited]),
        full_board=True,
        similarity=0.85,
    )
    assert updated == 1
    description = conn.execute("SELECT description_md FROM jobs").fetchone()
    payloads = conn.execute("SELECT count(*) FROM raw_payloads").fetchone()
    assert description is not None and "payments" in description[0]
    assert payloads == (2,)


def test_off_topic_titles_are_counted_as_skipped(conn) -> None:
    _company(conn)
    fetched, new_jobs, _, _, skipped = ingest_batch(
        conn,
        run_id=_run(conn),
        source_id="linkedin_guest",
        batch=FetchBatch(
            postings=[
                _posting(source_id="linkedin_guest", source_job_id="a", title="Accountant"),
                _posting(source_id="linkedin_guest", source_job_id="b", title="Software Engineer"),
            ]
        ),
        full_board=False,
        allowed_roles={"software"},
    )
    assert fetched == 1
    assert new_jobs == 1
    assert skipped == 1


def test_same_external_id_from_another_keyword_updates(conn) -> None:
    first_new = ingest_batch(
        conn,
        run_id=_run(conn, "linkedin_guest"),
        source_id="linkedin_guest",
        batch=FetchBatch(
            postings=[_posting(source_id="linkedin_guest", title="Software Engineer")]
        ),
        full_board=False,
    )[1]
    second_new = ingest_batch(
        conn,
        run_id=_run(conn, "linkedin_guest"),
        source_id="linkedin_guest",
        batch=FetchBatch(
            postings=[
                _posting(
                    source_id="linkedin_guest",
                    title="Software Engineer",
                    payload={"keyword": "backend"},
                )
            ]
        ),
        full_board=False,
    )[1]
    jobs = conn.execute("SELECT count(*) FROM jobs").fetchone()
    assert first_new == 1
    assert second_new == 0
    assert jobs == (1,)

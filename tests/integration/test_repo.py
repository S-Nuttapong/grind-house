from jobhunt.db import advisory_lock, close_pool, repo


def test_company_scope_run_job_posting_round_trip(conn) -> None:
    company_id = repo.insert_company(conn, name="Acme Pte Ltd", name_norm="acme", tier="A")
    repo.insert_alias(conn, "acme holdings", company_id)
    found = repo.get_company_by_name_norm(conn, "acme")
    assert found is not None
    assert found[0] == company_id

    scope_id = repo.insert_scope(
        conn,
        name="Greenhouse A",
        source_id="greenhouse",
        params={"tiers": ["A"]},
        cron="0 7 * * *",
    )
    scope = repo.get_scope(conn, scope_id)
    assert scope is not None
    assert scope[2] == "greenhouse"

    run_id = repo.start_run(
        conn,
        source_id="greenhouse",
        scraper_version="0.1.0",
        scope_id=scope_id,
    )
    job_id = repo.insert_job(
        conn,
        company_id=company_id,
        title="Senior Engineer",
        title_norm="senior engineer",
        apply_url="https://example.com/jobs/1",
        dedupe_key=f"{company_id}|senior engineer|SG",
        country="SG",
    )
    posting_id = repo.insert_posting(
        conn,
        job_id=job_id,
        source_id="greenhouse",
        source_job_id="99",
        source_url="https://example.com/jobs/1",
        content_hash="abc",
        run_id=run_id,
    )
    repo.insert_raw_payload(conn, posting_id=posting_id, run_id=run_id, payload={"id": 99})
    repo.finish_run(conn, run_id, status="ok", fetched=1, new_jobs=1)

    assert repo.get_job(conn, job_id) is not None
    assert repo.get_posting(conn, "greenhouse", "99") is not None
    status = conn.execute("SELECT status, new_jobs FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert status == ("ok", 1)


def test_only_one_advisory_lock(database_url: str) -> None:
    close_pool()
    with advisory_lock("jobhunt.tick") as first:
        assert first is True
        with advisory_lock("jobhunt.tick") as second:
            assert second is False
    with advisory_lock("jobhunt.tick") as third:
        assert third is True
    close_pool()
    _ = database_url

"""Seed is idempotent. Doctor reports a reachable migrated database."""

from pathlib import Path

from jobhunt.doctor import doctor
from jobhunt.scrape.seed import apply_seed


def test_seed_inserts_once(conn) -> None:
    config = Path(__file__).resolve().parents[2] / "config"
    first_companies, first_scopes = apply_seed(conn, config)
    second_companies, second_scopes = apply_seed(conn, config)
    assert first_companies >= 29
    assert first_scopes == 3
    assert (second_companies, second_scopes) == (0, 0)


def test_job_board_sources_exist(conn) -> None:
    rows = conn.execute(
        """
        SELECT id FROM sources
        WHERE id IN ('naukri', 'adzuna', 'reed', 'jooble', 'mycareersfuture', 'seek')
        """
    ).fetchall()
    assert {str(row[0]) for row in rows} == {
        "naukri",
        "adzuna",
        "reed",
        "jooble",
        "mycareersfuture",
        "seek",
    }


def test_doctor_reports_migrations(conn, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_BANK_PATH", str(tmp_path))
    problems, summary = doctor()
    assert problems == []
    assert "jobs" in summary
    _ = conn

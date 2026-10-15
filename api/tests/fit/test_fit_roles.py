"""Title grid, lineup text, and hand-review checks. No database and no model calls."""

import pytest
from jobhunt.fit.benchmark import BenchmarkError
from jobhunt.fit.roles import (
    RoleJob,
    draw_role_sample,
    grok_row_errors,
    jobs_outside,
    lineup_cell,
    render_compare,
    title_in_role_grid,
)


def _job(job_id: int, title: str) -> RoleJob:
    return RoleJob(job_id=job_id, title=title, company="Acme", description=title)


def test_role_grid_keeps_senior_lead_and_unlabeled_titles() -> None:
    assert title_in_role_grid("Senior Software Engineer")
    assert title_in_role_grid("Sr. Full-Stack Engineer")
    assert title_in_role_grid("Lead Frontend Engineer")
    assert title_in_role_grid("Software Engineer")
    assert title_in_role_grid("Product Engineer")
    assert title_in_role_grid("Growth Engineer")
    assert title_in_role_grid("Senior Software Engineer, Frontend")


def test_role_grid_drops_excluded_levels_and_other_roles() -> None:
    assert not title_in_role_grid("Staff Software Engineer")
    assert not title_in_role_grid("Principal Frontend Engineer")
    assert not title_in_role_grid("Engineering Manager")
    assert not title_in_role_grid("Senior Engineering Manager")
    assert not title_in_role_grid("Intern Software Engineer")
    assert not title_in_role_grid("New Grad Software Engineer")
    assert not title_in_role_grid("Junior Frontend Engineer")
    assert not title_in_role_grid("Data Scientist")
    assert not title_in_role_grid("Web Engineer")


def test_role_sample_is_stable_and_sorted() -> None:
    jobs = [
        _job(3, "Software Engineer"),
        _job(1, "Staff Software Engineer"),
        _job(2, "Senior Frontend Engineer"),
        _job(4, "Lead Full Stack Engineer"),
        _job(5, "Product Engineer"),
    ]
    picked = draw_role_sample(jobs, n=2, seed=20261012)
    again = draw_role_sample(jobs, n=2, seed=20261012)
    assert [job.job_id for job in picked] == [job.job_id for job in again]
    assert picked == sorted(picked, key=lambda job: job.job_id)
    assert all(title_in_role_grid(job.title) for job in picked)
    with pytest.raises(BenchmarkError):
        draw_role_sample(jobs, n=8, seed=1)


def test_exclude_keeps_used_ids_out() -> None:
    jobs = [_job(1, "Software Engineer"), _job(2, "Software Engineer")]
    picked = draw_role_sample(jobs_outside(jobs, {1}), n=1, seed=1)
    assert [job.job_id for job in picked] == [2]


def test_lineup_cell_quotes_one_bullet_per_story() -> None:
    cell = lineup_cell([("BB-001", "Made the home page faster", "Core Web Vitals")])
    assert cell == 'BB-001 Made the home page faster, covers "Core Web Vitals"'


def test_compare_table_links_the_local_job_and_escapes_pipes() -> None:
    table = render_compare(
        [
            {
                "job_id": "2479",
                "title": "Senior Engineer | Web",
                "company": "Grab",
                "brief": "Builds the public site.",
                "qwen_score": "61",
                "qwen_lineup": 'BB-001 Home page, covers "speed"',
                "haiku_score": "62",
                "haiku_lineup": "",
                "grok_score": "74",
                "grok_lineup": 'BB-016 SEO, covers "traffic"',
            }
        ]
    )
    assert "[Senior Engineer \\| Web](http://127.0.0.1:3000/?jk=2479)" in table
    assert "| Grab |" in table
    assert "| 62 |" in table
    assert table.count("\n") == 3


def test_grok_row_errors_reject_an_unknown_story() -> None:
    errors = grok_row_errors(
        {"score": 140, "brief": "", "lineup": [{"doc_id": "nope", "aspect": ""}]},
        {"BB-001"},
    )
    text = " ".join(errors)
    assert "score" in text
    assert "brief" in text
    assert "nope" in text

"""Store a JobDetail on its posting and fill empty job columns from all postings."""

from typing import Any

from psycopg import Connection
from psycopg.types.json import Json

from jobhunt.facts.base import (
    LEVELS,
    ExperienceFact,
    FieldName,
    JobDetail,
    LocationFact,
    PayFact,
    TextFact,
)
from jobhunt.scrape.normalize.salary import normalize_salary

_JOB_TYPES = {"fulltime", "parttime", "contract", "internship", "temporary"}
_WORKPLACES = {"onsite", "hybrid", "remote"}


def save_facts(conn: Connection[Any], posting_id: int, detail: JobDetail, status: str) -> None:
    conn.execute(
        "UPDATE postings SET facts = %s, facts_status = %s WHERE id = %s",
        (Json(detail.model_dump(mode="json")), status, posting_id),
    )


def merge_facts(conn: Connection[Any], job_id: int) -> None:
    """Fill null job columns from posting facts. A value already stored is kept."""
    rows = conn.execute(
        "SELECT facts FROM postings WHERE job_id = %s AND facts IS NOT NULL",
        (job_id,),
    ).fetchall()
    details = [_load(row[0]) for row in rows]
    current = conn.execute(
        """
        SELECT country, city, remote, employment_type, salary_min, salary_max,
               salary_currency, salary_interval, posted_at, locations, countries,
               role, level, experience_min_years, experience_max_years
        FROM jobs WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    if current is None:
        return
    origins: dict[str, str] = {}
    locations = _best_locations(details)
    pay = _best_pay(details)
    job_type = _best_text(details, "job_type")
    workplace = _best_text(details, "workplace")
    role_fact = _best_text(details, "role")
    level_fact = _best_text(details, "level")
    primary = locations.value[0] if locations is not None and locations.value else None
    country = current[0] or (None if primary is None else primary.country)
    city = current[1] or (None if primary is None else primary.city)
    remote = current[2]
    if remote == "unknown" and workplace is not None and workplace.value in _WORKPLACES:
        remote = workplace.value
        origins["workplace"] = workplace.parser_id
    employment = current[3]
    if employment is None and job_type is not None and job_type.value in _JOB_TYPES:
        employment = job_type.value
        origins["job_type"] = job_type.parser_id
    salary_min = current[4]
    salary_max = current[5]
    salary_currency = current[6]
    salary_interval = current[7]
    posted_at = current[8]
    if salary_min is None and salary_max is None and pay is not None:
        low, high, code, interval, usd = normalize_salary(
            pay.value.minimum, pay.value.maximum, pay.value.currency, pay.value.interval
        )
        salary_min, salary_max, salary_currency, salary_interval = low, high, code, interval
        origins["pay"] = pay.parser_id
    else:
        usd = None
    if posted_at is None:
        posted = _best_posted(details)
        if posted is not None:
            posted_at = posted.value
            origins["posted"] = posted.parser_id
    role = current[11]
    if role is None and role_fact is not None:
        role = role_fact.value
        origins["role"] = role_fact.parser_id
    level = current[12]
    if level in (None, "unknown") and level_fact is not None and level_fact.value in LEVELS:
        level = level_fact.value
        origins["level"] = level_fact.parser_id
    experience = _best_experience(details)
    experience_min = current[13]
    experience_max = current[14]
    if experience_min is None and experience_max is None and experience is not None:
        experience_min = experience.value.minimum
        experience_max = experience.value.maximum
        origins["experience"] = experience.parser_id
    if primary is not None and (current[0] is None or current[1] is None):
        origins["locations"] = locations.parser_id if locations is not None else ""
    stored_locations = current[9]
    empty_locations = stored_locations in (None, []) or stored_locations == []
    location_json = (
        [place.model_dump() for place in locations.value]
        if locations is not None and empty_locations
        else None
    )
    stored_countries = current[10] or []
    countries = None
    if not stored_countries and locations is not None:
        countries = list(dict.fromkeys(place.country for place in locations.value if place.country))
    if usd is None and salary_min is not None and origins.get("pay"):
        usd = normalize_salary(salary_min, salary_max, salary_currency, salary_interval)[4]
    conn.execute(
        """
        UPDATE jobs SET
          country = %s,
          city = %s,
          remote = %s,
          employment_type = %s,
          salary_min = COALESCE(salary_min, %s),
          salary_max = COALESCE(salary_max, %s),
          salary_currency = COALESCE(salary_currency, %s),
          salary_interval = COALESCE(salary_interval, %s),
          salary_usd_year_min = COALESCE(salary_usd_year_min, %s),
          posted_at = %s,
          locations = CASE WHEN locations = '[]'::jsonb
            THEN COALESCE(%s::jsonb, locations) ELSE locations END,
          countries = CASE WHEN countries = '{}' THEN COALESCE(%s, countries) ELSE countries END,
          role = CASE WHEN role IS NULL THEN COALESCE(%s, role) ELSE role END,
          level = CASE WHEN level IS NULL OR level = 'unknown'
            THEN COALESCE(%s, level) ELSE level END,
          experience_min_years = COALESCE(experience_min_years, %s),
          experience_max_years = COALESCE(experience_max_years, %s),
          fact_origins = fact_origins || %s::jsonb
        WHERE id = %s
        """,
        (
            country,
            city,
            remote,
            employment,
            salary_min if origins.get("pay") else None,
            salary_max if origins.get("pay") else None,
            salary_currency if origins.get("pay") else None,
            salary_interval if origins.get("pay") else None,
            usd if origins.get("pay") else None,
            posted_at,
            Json(location_json) if location_json is not None else None,
            countries,
            role if origins.get("role") else None,
            level if origins.get("level") else None,
            experience_min if origins.get("experience") else None,
            experience_max if origins.get("experience") else None,
            Json(origins),
            job_id,
        ),
    )


def _load(payload: object) -> JobDetail:
    if isinstance(payload, str):
        return JobDetail.model_validate_json(payload)
    return JobDetail.model_validate(payload)


def _best_pay(details: list[JobDetail]) -> PayFact | None:
    facts = [detail.pay for detail in details if detail.pay is not None]
    return _best(facts)


def _best_text(details: list[JobDetail], field: FieldName) -> TextFact | None:
    facts: list[TextFact] = []
    for detail in details:
        fact = getattr(detail, field)
        if isinstance(fact, TextFact):
            facts.append(fact)
    return _best(facts)


def _best_experience(details: list[JobDetail]) -> ExperienceFact | None:
    facts = [detail.experience for detail in details if detail.experience is not None]
    return _best(facts)


def _best_locations(details: list[JobDetail]) -> LocationFact | None:
    facts = [detail.locations for detail in details if detail.locations is not None]
    return _best(facts)


def _best_posted(details: list[JobDetail]) -> Any:
    facts = [detail.posted for detail in details if detail.posted is not None]
    return _best(facts)


def _best[T](facts: list[T]) -> T | None:
    if not facts:
        return None

    def sort_key(fact: T) -> tuple[int, float]:
        parser_id = str(getattr(fact, "parser_id", ""))
        rank = 0 if parser_id.startswith("api:") else 1
        confidence = float(getattr(fact, "confidence", 0))
        return (rank, -confidence)

    return sorted(facts, key=sort_key)[0]

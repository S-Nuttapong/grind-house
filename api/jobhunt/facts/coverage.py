"""How many open jobs still lack each Job details field, per source."""

from typing import Any

from psycopg import Connection

_SQL = """
SELECT p.source_id,
       count(DISTINCT j.id) AS jobs,
       count(DISTINCT j.id) FILTER (WHERE j.country IS NULL) AS no_country,
       count(DISTINCT j.id) FILTER (WHERE j.city IS NULL) AS no_city,
       count(DISTINCT j.id) FILTER (WHERE j.remote = 'unknown') AS unknown_workplace,
       count(DISTINCT j.id) FILTER (WHERE j.employment_type IS NULL) AS no_type,
       count(DISTINCT j.id) FILTER (WHERE NOT EXISTS (
           SELECT 1 FROM job_compensation c WHERE c.job_id = j.id AND c.type = 'base'
       )) AS no_pay,
       count(DISTINCT j.id) FILTER (WHERE j.posted_at IS NULL) AS no_posted,
       count(DISTINCT j.id) FILTER (WHERE j.role IS NULL) AS no_role,
       count(DISTINCT j.id) FILTER (WHERE j.level = 'unknown') AS unknown_level,
       count(DISTINCT j.id) FILTER (
           WHERE j.country IS NULL OR j.locations = '[]'::jsonb
       ) AS no_location,
       count(DISTINCT j.id) FILTER (
           WHERE j.experience_min_months IS NULL AND j.experience_max_months IS NULL
       ) AS no_experience
FROM jobs j
JOIN postings p ON p.job_id = j.id
WHERE j.closed_at IS NULL
GROUP BY p.source_id
ORDER BY p.source_id
"""


def coverage_rows(conn: Connection[Any]) -> list[dict[str, int | str]]:
    rows = conn.execute(_SQL).fetchall()
    return [
        {
            "source": str(row[0]),
            "jobs": int(row[1]),
            "no_country": int(row[2]),
            "no_city": int(row[3]),
            "unknown_workplace": int(row[4]),
            "no_type": int(row[5]),
            "no_pay": int(row[6]),
            "no_posted": int(row[7]),
            "no_role": int(row[8]),
            "unknown_level": int(row[9]),
            "no_location": int(row[10]),
            "no_experience": int(row[11]),
        }
        for row in rows
    ]


def coverage_table(conn: Connection[Any]) -> str:
    header = (
        "source",
        "jobs",
        "no_country",
        "no_city",
        "unknown_workplace",
        "no_type",
        "no_pay",
        "no_posted",
        "no_role",
        "unknown_level",
        "no_location",
        "no_experience",
    )
    lines = ["\t".join(header)]
    for row in coverage_rows(conn):
        lines.append("\t".join(str(row[column]) for column in header))
    return "\n".join(lines)

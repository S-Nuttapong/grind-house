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
       count(DISTINCT j.id) FILTER (WHERE j.salary_min IS NULL AND j.salary_max IS NULL) AS no_pay,
       count(DISTINCT j.id) FILTER (WHERE j.posted_at IS NULL) AS no_posted
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
    )
    lines = ["\t".join(header)]
    for row in coverage_rows(conn):
        lines.append("\t".join(str(row[column]) for column in header))
    return "\n".join(lines)

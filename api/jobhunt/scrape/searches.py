"""Turn a saved search into one request per board and country."""

from typing import Any


def or_query(keywords: list[str]) -> str:
    """One query for every keyword. Multi-word phrases stay quoted."""
    parts = [f'"{word}"' if " " in word else word for word in keywords if word.strip()]
    return " OR ".join(parts)


def expand(search: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Yield ``(source_id, country, params)``.

    Every board gets the same OR query. A separate query per keyword would
    multiply requests by six for the same jobs, and the SEEK search accepts OR.
    """
    from jobhunt.scrape.markets import board, location

    query = or_query(list(search.get("keywords") or []))
    if not query:
        return []
    found: list[tuple[str, str, dict[str, Any]]] = []
    for source_id in search.get("sources") or []:
        for country in search.get("countries") or []:
            code = str(country).upper()
            entry = board(code, str(source_id))
            if entry is None:
                continue
            found.append(
                (str(source_id), code, _params(str(source_id), code, query, entry, location(code)))
            )
    return found


def _params(
    source_id: str,
    country: str,
    query: str,
    entry: dict[str, Any],
    where: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {"search_term": query, "country": country, "location": where}
    if source_id == "linkedin_guest":
        params["geo_id"] = str(entry["geo_id"])
    elif source_id in {"indeed", "glassdoor"}:
        params["country_indeed"] = str(entry["country_indeed"])
        if entry.get("location"):
            params["location"] = str(entry["location"])
    elif source_id == "seek":
        params["host"] = str(entry["host"])
        params["site_key"] = str(entry["site_key"])
    elif source_id == "adzuna":
        params["country"] = str(entry["country"])
    elif source_id == "jooble":
        params["host"] = str(entry["host"])
    elif source_id == "naukri" and entry.get("location"):
        params["location"] = str(entry["location"])
    elif source_id == "reed" and entry.get("location"):
        params["location"] = str(entry["location"])
    return params

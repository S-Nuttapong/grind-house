"""Filter parsing drops values that are not in the allowlist."""

from jobhunt.jobs.queries import parse_filters


def test_parse_filters_keeps_known_values_and_drops_the_rest() -> None:
    filters = parse_filters(
        {
            "country": "SG,ZZ,th",
            "role": "frontend,nope",
            "region": "apac,mars",
            "industry": "fintech",
            "level": "senior,boss",
            "remote": "remote,office",
            "source": "indeed,Bad Source",
            "min_score": "65",
        }
    )
    assert filters["country"] == ["SG", "TH"]
    assert filters["role"] == ["frontend"]
    assert filters["region"] == ["apac"]
    assert filters["industry"] == ["fintech"]
    assert filters["level"] == ["senior"]
    assert filters["remote"] == ["remote"]
    assert filters["source"] == ["indeed"]
    assert filters["min_score"] == 65


def test_min_score_outside_0_to_100_is_ignored() -> None:
    assert parse_filters({"min_score": "101"})["min_score"] is None
    assert parse_filters({"min_score": "-1"})["min_score"] is None


def test_sort_defaults_to_newest_and_keeps_old_names() -> None:
    assert parse_filters({})["sort"] == "newest"
    assert parse_filters({"sort": "nope"})["sort"] == "newest"
    assert parse_filters({"sort": "oldest"})["sort"] == "oldest"
    assert parse_filters({"sort": "fit_asc"})["sort"] == "fit_asc"
    assert parse_filters({"sort": "posted"})["sort"] == "newest"
    assert parse_filters({"sort": "first_seen"})["sort"] == "newest"
    assert parse_filters({"sort": "match"})["sort"] == "fit_desc"

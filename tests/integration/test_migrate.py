import pytest
from jobhunt.db.migrate import migrate


@pytest.mark.integration
def test_migrate_up_down_up_leaves_sources(database_url: str) -> None:
    """The session fixture already cycled up/down/up. Sources from the seed remain."""
    import psycopg

    with psycopg.connect(database_url) as connection:
        row = connection.execute("SELECT count(*) FROM sources").fetchone()
    assert row is not None
    assert row[0] == 10


def test_migrate_rejects_unknown_direction() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        migrate("sideways")

"""Persistence handle for the pipelines. The SQL stays in the repos."""

from typing import Protocol

from jobhunt.core.db import tx
from jobhunt.scrape import repo


class Store(Protocol):
    """What a pipeline is allowed to ask persistence for."""

    def scrape_targets(
        self, *, scope_id: int | None, source_id: str | None
    ) -> list[tuple[int, str]]: ...


class PgStore:
    """Reads and writes through the existing repos."""

    def scrape_targets(
        self, *, scope_id: int | None, source_id: str | None
    ) -> list[tuple[int, str]]:
        with tx() as conn:
            if scope_id is not None:
                scope = repo.get_scope(conn, scope_id)
                if scope is None:
                    raise ValueError(f"fetch scope {scope_id} does not exist")
                return [(int(scope[0]), str(scope[2]))]
            if source_id is None:
                raise ValueError("pass either --scope or --source")
            rows = repo.list_scopes_for_source(conn, source_id)
            return [(int(row[0]), str(row[2])) for row in rows]

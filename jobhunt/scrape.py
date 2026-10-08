"""Run one scope, or every enabled scope for a source."""

from jobhunt.db import repo, tx
from jobhunt.ingest import RunResult, run_scope
from jobhunt.sources.registry import adapter_for


def scrape(*, scope_id: int | None, source_id: str | None) -> list[RunResult]:
    if scope_id is not None and source_id is not None:
        raise ValueError("pass either --scope or --source, not both")
    with tx() as conn:
        if scope_id is not None:
            scope = repo.get_scope(conn, scope_id)
            if scope is None:
                raise ValueError(f"fetch scope {scope_id} does not exist")
            targets = [(int(scope[0]), str(scope[2]))]
        else:
            if source_id is None:
                raise ValueError("pass either --scope or --source")
            rows = repo.list_scopes_for_source(conn, source_id)
            targets = [(int(row[0]), str(row[2])) for row in rows]
    results: list[RunResult] = []
    for target_id, target_source in targets:
        results.append(run_scope(target_id, adapter_for(target_source)))
    return results

"""Acceptance checks for one stored resume run. The browser checks live in the UAT spec."""

import io
from typing import Any

from psycopg import Connection
from pypdf import PdfReader

from jobhunt.fit import repo as fit_repo
from jobhunt.resume import repo
from jobhunt.resume.worker import max_cost

_FIVE_MINUTES = 300


def check_run(conn: Connection[Any], run_id: int) -> list[tuple[str, bool, str]]:
    """Return (name, passed, detail) for the checks that do not need a browser."""
    run = repo.get_run(conn, run_id)
    if run is None:
        return [("run", False, "no such run")]
    artifact = repo.artifact(conn, run_id)
    usage = repo.usage_for_run(conn, run_id)
    checks = [
        _status(run),
        _pdf(artifact),
        _lint(artifact),
        _citations(conn, run, artifact),
        _gate(run),
        _cost(usage),
        _duration(run),
    ]
    return checks


def _status(run: dict[str, Any]) -> tuple[str, bool, str]:
    status = str(run["status"])
    return ("status", status == "ok", status)


def _pdf(artifact: dict[str, Any] | None) -> tuple[str, bool, str]:
    if artifact is None:
        return ("pdf", False, "no pdf stored")
    reader = PdfReader(_buffer(artifact["pdf"]))
    pages = len(reader.pages)
    return ("pdf", pages == 1, f"{pages} page(s)")


def _lint(artifact: dict[str, Any] | None) -> tuple[str, bool, str]:
    if artifact is None:
        return ("lint", False, "no lint report")
    report = str(artifact["lint_report"])
    if not report.strip():
        return ("lint", False, "empty lint report")
    has_fail = "| FAIL |" in report
    return ("lint", not has_fail, "clean" if not has_fail else "FAIL present")


def _citations(
    conn: Connection[Any], run: dict[str, Any], artifact: dict[str, Any] | None
) -> tuple[str, bool, str]:
    if artifact is None:
        return ("citations", False, "no resume")
    resume = artifact["resume_json"]
    if isinstance(resume, str):
        import json

        resume = json.loads(resume)
    from jobhunt.resume.gate import cited_ids

    cited = cited_ids(resume if isinstance(resume, dict) else {})
    matches = fit_repo.matches_for(
        conn, int(run["job_id"]), str(run["fit_model_id"]), str(run["fit_source_hash"])
    )
    shortlist = [str(item["id"]) for item in matches]
    missing = [doc_id for doc_id in shortlist if doc_id not in cited]
    unknown = [
        doc_id
        for doc_id in cited
        if doc_id != "profile"
        and conn.execute("SELECT 1 FROM brag_docs WHERE id = %s", (doc_id,)).fetchone() is None
    ]
    detail = f"missing {missing}; unknown {unknown}" if missing or unknown else "all cited"
    return ("citations", not missing and not unknown, detail)


def _gate(run: dict[str, Any]) -> tuple[str, bool, str]:
    lost = list(run["lost_aspects"] or [])
    resume_score = run["resume_score"]
    baseline = run["baseline_score"]
    if resume_score is None or baseline is None:
        return ("gate", False, "scores were not recorded")
    ok = float(resume_score) + 0.05 >= float(baseline) and not lost
    return ("gate", ok, f"resume {resume_score} baseline {baseline} lost {lost}")


def _cost(usage: list[dict[str, Any]]) -> tuple[str, bool, str]:
    if not usage:
        return ("cost", False, "no usage row")
    total = sum(item["cost_usd"] for item in usage)
    ok = total > 0 and total <= max_cost()
    return ("cost", ok, f"${total} of ${max_cost()}")


def _duration(run: dict[str, Any]) -> tuple[str, bool, str]:
    started = run["started_at"]
    finished = run["finished_at"]
    if started is None or finished is None:
        return ("duration", False, "run has no timestamps")
    seconds = (finished - started).total_seconds()
    return ("duration", seconds < _FIVE_MINUTES, f"{int(seconds)}s")


def _buffer(pdf: object) -> io.BytesIO:
    if isinstance(pdf, memoryview):
        return io.BytesIO(pdf.tobytes())
    if isinstance(pdf, bytes | bytearray):
        return io.BytesIO(pdf)
    raise TypeError("stored pdf is not bytes")

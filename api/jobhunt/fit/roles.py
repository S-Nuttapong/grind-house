"""Thirty-job comparison of Qwen, Haiku, and a hand review on the brag bank.

The sample is jobs Qwen already scored, filtered by title. Scoring here does not
write job_fits. Qwen and Haiku run against the brag bank, not the one-section resume.
"""

import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from jobhunt.fit.base import BragDoc, FitResult
from jobhunt.fit.benchmark import BenchmarkError

ROLE_SAMPLE_SIZE = 30
GOLD_SAMPLE_SIZE = 100
ROLE_SEED = 20261012
BOARD_URL = "http://127.0.0.1:3000"

_EXCLUDED_LEVEL = re.compile(
    r"\b(?:staff|principal|directors?|heads?|managers?|intern(?:ship)?s?"
    r"|new\s*grads?|juniors?|jr\.?|stages?)\b",
    re.IGNORECASE,
)
_ROLE = re.compile(
    r"front[\s-]?end|\bfe\b|full[\s-]?stack|\bswe\b|software\s+engineers?"
    r"|product\s+engineers?|growth\s+engineers?",
    re.IGNORECASE,
)

_OPEN_SQL = """
SELECT j.id, j.title, c.name, j.description_md
FROM job_fits f
JOIN jobs j ON j.id = f.job_id
JOIN companies c ON c.id = j.company_id
WHERE j.closed_at IS NULL
  AND f.model_id = %s
  AND f.source_hash = %s
ORDER BY j.id
"""


@dataclass(frozen=True)
class RoleJob:
    job_id: int
    title: str
    company: str
    description: str


def title_in_role_grid(title: str) -> bool:
    """Senior, lead, or unlabeled frontend, full-stack, SWE, product, or growth titles."""
    if _EXCLUDED_LEVEL.search(title):
        return False
    return _ROLE.search(title) is not None


def draw_role_sample(jobs: Sequence[RoleJob], *, n: int, seed: int) -> list[RoleJob]:
    """Draw n titles from the grid. Callers pass jobs sorted by id so the seed is stable."""
    if n < 0:
        raise BenchmarkError("sample size cannot be negative")
    matched = [job for job in jobs if title_in_role_grid(job.title)]
    if n > len(matched):
        raise BenchmarkError(f"role grid has {len(matched)} jobs, need {n}")
    picked = random.Random(seed).sample(list(matched), n)
    return sorted(picked, key=lambda job: job.job_id)


def read_open_jobs(conn: Any, *, model_id: str, source_hash: str) -> list[RoleJob]:
    rows = conn.execute(_OPEN_SQL, (model_id, source_hash)).fetchall()
    return [
        RoleJob(
            job_id=int(job_id),
            title=str(title),
            company=str(company),
            description=str(description or title),
        )
        for job_id, title, company, description in rows
    ]


def jobs_outside(jobs: Sequence[RoleJob], exclude: set[int]) -> list[RoleJob]:
    """Drop job ids that were already used, keeping the input order."""
    return [job for job in jobs if job.job_id not in exclude]


def prepare_sample(
    conn: Any,
    out: Path,
    *,
    n: int = ROLE_SAMPLE_SIZE,
    seed: int = ROLE_SEED,
    exclude: set[int] | None = None,
) -> Path:
    """Freeze the jobs and brag stories. Scores are not included."""
    from jobhunt.fit.matrix import QWEN3
    from jobhunt.fit.sources import bank_docs, current_docs, docs_hash

    conn.execute("SET TRANSACTION READ ONLY")
    resume_hash = docs_hash(current_docs(conn, "resume"))
    jobs = read_open_jobs(conn, model_id=QWEN3.model_id, source_hash=resume_hash)
    selected = draw_role_sample(jobs_outside(jobs, exclude or set()), n=n, seed=seed)
    docs = bank_docs(conn)
    payload = {
        "seed": seed,
        "n": n,
        "resume_source_hash": resume_hash,
        "docs": [_doc_record(doc) for doc in docs],
        "jobs": [_job_record(job) for job in selected],
    }
    path = out / "sample.json"
    _write_json(path, payload)
    return path


def lineup_cell(picks: Sequence[tuple[str, str, str]]) -> str:
    """One story per line: id, title, and the single bullet it matches best."""
    lines: list[str] = []
    for doc_id, title, aspect in list(picks)[:10]:
        bullet = " ".join(aspect.split())
        if len(bullet) > 140:
            bullet = bullet[:137] + "..."
        lines.append(f'{doc_id} {title}, covers "{bullet}"')
    return "<br>".join(lines)


def render_compare(rows: Sequence[dict[str, str]]) -> str:
    header = (
        "| Title | Company | Brief | Qwen score | Qwen brag lineup "
        "| Haiku score | Haiku brag lineup | Grok 4.7 score | Grok 4.7 brag lineup |"
    )
    rule = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    body = [
        "| "
        + " | ".join(
            [
                _link(row),
                _cell(row["company"]),
                _cell(row["brief"]),
                _cell(row["qwen_score"]),
                _cell(row["qwen_lineup"]),
                _cell(row["haiku_score"]),
                _cell(row["haiku_lineup"]),
                _cell(row["grok_score"]),
                _cell(row["grok_lineup"]),
            ]
        )
        + " |"
        for row in rows
    ]
    return "\n".join([header, rule, *body]) + "\n"


def grok_row_errors(row: dict[str, Any], doc_ids: set[str]) -> list[str]:
    errors: list[str] = []
    score = row.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
        errors.append("score is outside 0 to 100")
    brief = row.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        errors.append("brief is empty")
    lineup = row.get("lineup")
    if not isinstance(lineup, list):
        errors.append("lineup is missing")
        return errors
    if len(lineup) > 10:
        errors.append("lineup has more than 10 stories")
    seen: set[str] = set()
    for index, pick in enumerate(lineup):
        if not isinstance(pick, dict):
            errors.append(f"lineup {index} is not an object")
            continue
        doc_id = str(pick.get("doc_id", ""))
        if doc_id not in doc_ids:
            errors.append(f"lineup {index} doc_id {doc_id!r} is unknown")
        elif doc_id in seen:
            errors.append(f"lineup {index} doc_id {doc_id!r} is repeated")
        seen.add(doc_id)
        aspect = pick.get("aspect")
        if not isinstance(aspect, str) or not aspect.strip():
            errors.append(f"lineup {index} aspect is empty")
    return errors


def _doc_record(doc: BragDoc) -> dict[str, str]:
    title, _, _rest = doc.text.partition("\n")
    return {"id": doc.id, "title": title.strip() or doc.id, "text": doc.text}


def _job_record(job: RoleJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "description": job.description,
    }


def _link(row: dict[str, str]) -> str:
    title = _cell(row["title"]).replace("[", "\\[").replace("]", "\\]")
    return f"[{title}]({BOARD_URL}/?jk={row['job_id']})"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def qwen_picks(result: FitResult, titles: dict[str, str]) -> list[tuple[str, str, str]]:
    return [
        (match.brag_doc_id, titles.get(match.brag_doc_id, match.brag_doc_id), match.aspect)
        for match in result.top_docs
    ]


def score_models(sample_path: Path, dest: Path) -> None:
    """Score the frozen sample with Qwen and Haiku. Does not read or write a hand review."""
    from decimal import Decimal
    from typing import Any as AnyType

    from jobhunt.composition import require_on_machine
    from jobhunt.core.claude import structured_call
    from jobhunt.fit import claude as claude_fit
    from jobhunt.fit.base import FitUnavailable
    from jobhunt.fit.claude import ClaudeFitScorer
    from jobhunt.fit.matrix import MatrixFitScorer

    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    docs = [
        BragDoc(id=str(doc["id"]), text=str(doc["text"]))
        for doc in payload["docs"]
        if str(doc["id"]).startswith("BB-")
    ]
    titles = {doc.id: doc.text.split("\n", 1)[0].strip() or doc.id for doc in docs}
    print("loading qwen", flush=True)
    qwen = MatrixFitScorer("qwen3")
    haiku = ClaudeFitScorer()
    require_on_machine(haiku, "fit scorer")
    descriptions = [str(job["description"]) for job in payload["jobs"]]
    print("scoring qwen", flush=True)
    qwen_results = qwen.fit_many(docs, descriptions)
    captured: list[AnyType] = []

    def recording(**kwargs: Any) -> tuple[Any, Any]:
        parsed, meta = structured_call(**kwargs)
        captured.append(meta)
        return parsed, meta

    module: Any = claude_fit
    previous = module.structured_call
    module.structured_call = recording
    rows: list[dict[str, Any]] = []
    try:
        for index, job in enumerate(payload["jobs"], start=1):
            description = str(job["description"])
            qwen_result = qwen_results[index - 1]
            before = len(captured)
            haiku_result: FitResult | None = None
            error: str | None = None
            try:
                haiku_result = haiku.fit(docs, description)
            except FitUnavailable as exc:
                error = str(exc)
            calls = captured[before:]
            rows.append(
                {
                    "job_id": int(job["job_id"]),
                    "qwen_score": qwen_result.score,
                    "qwen_lineup": [
                        {"doc_id": doc_id, "title": title, "aspect": aspect}
                        for doc_id, title, aspect in qwen_picks(qwen_result, titles)
                    ],
                    "haiku_score": None if haiku_result is None else haiku_result.score,
                    "haiku_lineup": []
                    if haiku_result is None
                    else [
                        {"doc_id": doc_id, "title": title, "aspect": aspect}
                        for doc_id, title, aspect in qwen_picks(haiku_result, titles)
                    ],
                    "haiku_error": error,
                    "haiku_cost_usd": format(
                        sum((call.cost_usd for call in calls), Decimal("0")), "f"
                    ),
                }
            )
            print(f"scored {index}/{len(payload['jobs'])} job {job['job_id']}", flush=True)
    finally:
        module.structured_call = previous
    spent = sum((Decimal(row["haiku_cost_usd"]) for row in rows), Decimal("0"))
    _write_json(dest, {"jobs": rows, "haiku_cost_usd": format(spent, "f")})


def score_haiku(sample_path: Path, prior_scores: Path, dest: Path) -> None:
    """Rescore Haiku only. Qwen rows come from a previous score file."""
    from decimal import Decimal
    from typing import Any as AnyType

    from jobhunt.composition import require_on_machine
    from jobhunt.core.claude import ClaudeError, structured_call
    from jobhunt.fit import claude as claude_fit
    from jobhunt.fit.base import FitUnavailable
    from jobhunt.fit.claude import ClaudeFitScorer

    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    prior = json.loads(prior_scores.read_text(encoding="utf-8"))
    prior_by_id = {int(row["job_id"]): row for row in prior["jobs"]}
    docs = [
        BragDoc(id=str(doc["id"]), text=str(doc["text"]))
        for doc in payload["docs"]
        if str(doc["id"]).startswith("BB-")
    ]
    titles = {doc.id: doc.text.split("\n", 1)[0].strip() or doc.id for doc in docs}
    haiku = ClaudeFitScorer()
    require_on_machine(haiku, "fit scorer")
    captured: list[AnyType] = []

    def recording(**kwargs: Any) -> tuple[Any, Any]:
        parsed, meta = structured_call(**kwargs)
        captured.append(meta)
        return parsed, meta

    module: Any = claude_fit
    previous = module.structured_call
    module.structured_call = recording
    rows: list[dict[str, Any]] = []
    try:
        for index, job in enumerate(payload["jobs"], start=1):
            job_id = int(job["job_id"])
            qwen = prior_by_id[job_id]
            before = len(captured)
            haiku_result: FitResult | None = None
            error: str | None = None
            try:
                haiku_result = haiku.fit(docs, str(job["description"]))
            except FitUnavailable as exc:
                error = str(exc)
                cause = exc.__cause__
                if isinstance(cause, ClaudeError):
                    captured.extend(cause.calls)
            calls = captured[before:]
            rows.append(
                {
                    "job_id": job_id,
                    "qwen_score": qwen["qwen_score"],
                    "qwen_lineup": qwen["qwen_lineup"],
                    "haiku_score": None if haiku_result is None else haiku_result.score,
                    "haiku_lineup": []
                    if haiku_result is None
                    else [
                        {"doc_id": doc_id, "title": title, "aspect": aspect}
                        for doc_id, title, aspect in qwen_picks(haiku_result, titles)
                    ],
                    "haiku_error": error,
                    "haiku_cost_usd": format(
                        sum((call.cost_usd for call in calls), Decimal("0")), "f"
                    ),
                }
            )
            print(f"scored {index}/{len(payload['jobs'])} job {job_id}", flush=True)
    finally:
        module.structured_call = previous
    spent = sum((Decimal(row["haiku_cost_usd"]) for row in rows), Decimal("0"))
    _write_json(dest, {"jobs": rows, "haiku_cost_usd": format(spent, "f")})


class GoldError(ValueError):
    """The gold file is missing, incomplete, or was not written by the teacher."""


class GoldUnstable(GoldError):
    """The teacher did not agree with itself. Do not optimize against these labels."""


class GoldBudget(GoldError):
    """Label spend reached the cap. The file is incomplete."""


class _GoldFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int
    docs: list[str]
    reason: str


@dataclass(frozen=True)
class GoldJob:
    job_id: int
    rating: int
    docs: tuple[str, ...]
    reason: str
    model: str
    cost_usd: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


_LABEL_RUBRIC = """Rate how well the stories below fit the job in the user message.
rating is an integer from 1 to 5.
5 means apply now, a strong fit.
4 means a good fit.
3 means maybe.
2 means a weak fit.
1 means not my job.
docs lists up to 10 story ids, best first, copied from the stories below.
Put a story in docs only if it would go on a resume for this job.
An empty list is allowed.
Do not invent a story id.
reason is one sentence.
"""

_CALL_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def load_sample(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "jobs" not in payload or "docs" not in payload:
        raise BenchmarkError(f"{path} is missing jobs or docs")
    return payload


def split_fit_jobs(
    job_ids: Sequence[int], *, seed: int = ROLE_SEED, dev_n: int = 60
) -> tuple[list[int], list[int]]:
    """Seeded dev/test split. The same ids and seed always return the same halves."""
    ids = sorted(set(job_ids))
    if dev_n < 1 or dev_n >= len(ids):
        raise BenchmarkError(f"dev split {dev_n} does not fit {len(ids)} jobs")
    order = random.Random(seed).sample(ids, len(ids))
    return sorted(order[:dev_n]), sorted(order[dev_n:])


def load_fit_gold(path: Path, doc_ids: set[str], job_ids: set[int]) -> list[GoldJob]:
    """Refuse a file the teacher did not finish: bad model, missing call, or missing job."""
    from jobhunt.fit.optimize import TEACHER_MODEL

    labeler, entries = _read_gold(path)
    if labeler != TEACHER_MODEL:
        raise GoldError("labeler is not the teacher model")
    found: dict[int, GoldJob] = {}
    for item in entries:
        job = _gold_job(item, doc_ids)
        if job.model != TEACHER_MODEL:
            raise GoldError(f"job {job.job_id} model is not the teacher")
        found[job.job_id] = job
    missing = sorted(set(job_ids) - set(found))
    if missing:
        raise GoldError(f"gold file is missing {len(missing)} jobs")
    return [found[job_id] for job_id in sorted(job_ids)]


def label_fit_gold(sample: Path, dest: Path, *, budget_usd: Decimal | None = None) -> Path:
    """Label every sample job with the teacher. Jobs already in dest are skipped."""
    from jobhunt.fit.optimize import LABEL_BUDGET_USD, TEACHER_MODEL, preflight_teacher

    budget = LABEL_BUDGET_USD if budget_usd is None else budget_usd
    payload = load_sample(sample)
    docs = _sample_docs(payload)
    doc_ids = {doc.id for doc in docs}
    labeler, entries = _read_gold(dest) if dest.is_file() else (None, [])
    if labeler not in {None, TEACHER_MODEL}:
        raise GoldError("labeler is not the teacher model")
    for item in entries:
        _gold_job(item, doc_ids)
    done = {int(item["job_id"]) for item in entries}
    spent = _labeled_spend(entries)
    pending = [job for job in payload["jobs"] if int(job["job_id"]) not in done]
    if not pending:
        _write_gold(dest, entries)
        return dest
    meta = preflight_teacher()
    spent += meta.cost_usd
    system = _label_system(docs)
    for index, job in enumerate(pending, start=1):
        if spent >= budget:
            _write_gold(dest, entries)
            raise GoldBudget(f"label spend reached {spent} of {budget}")
        try:
            parsed, calls = _label_job(system, job, doc_ids)
        except GoldError as exc:
            _write_gold(dest, entries)
            raise GoldError(f"job {job['job_id']}: {exc}") from exc
        spent += sum((call.cost_usd for call in calls), Decimal("0"))
        entries.append(_label_entry(int(job["job_id"]), parsed, calls[-1]))
        _write_gold(dest, entries)
        print(f"labeled {index}/{len(pending)} job {job['job_id']} spent_usd={spent}", flush=True)
    _write_gold(dest, entries)
    return dest


def check_label_stability(
    sample: Path,
    gold: Path,
    dest: Path,
    *,
    n: int = 10,
    budget_usd: Decimal | None = None,
) -> dict[str, Any]:
    """Relabel n seeded jobs from scratch. Stop when the teacher disagrees with itself."""
    from jobhunt.fit.optimize import LABEL_BUDGET_USD

    budget = LABEL_BUDGET_USD if budget_usd is None else budget_usd
    payload = load_sample(sample)
    docs = _sample_docs(payload)
    doc_ids = {doc.id for doc in docs}
    job_ids = {int(job["job_id"]) for job in payload["jobs"]}
    labels = {job.job_id: job for job in load_fit_gold(gold, doc_ids, job_ids)}
    if n > len(labels):
        raise GoldError(f"cannot relabel {n} jobs from {len(labels)}")
    chosen = random.Random(ROLE_SEED).sample(sorted(labels), n)
    by_id = {int(job["job_id"]): job for job in payload["jobs"]}
    system = _label_system(docs)
    spent = _gold_file_spend(gold)
    rows: list[dict[str, Any]] = []
    for job_id in chosen:
        if spent >= budget:
            _write_stability(dest, rows, stable=False, blocked="budget")
            raise GoldBudget(f"label spend reached {spent} of {budget}")
        parsed, calls = _label_job(system, by_id[job_id], doc_ids)
        spent += sum((call.cost_usd for call in calls), Decimal("0"))
        original = labels[job_id]
        overlap = _jaccard(original.docs, parsed.docs)
        rows.append(
            {
                "job_id": job_id,
                "rating": original.rating,
                "relabel": parsed.rating,
                "within_1": abs(original.rating - parsed.rating) <= 1,
                "jaccard": overlap,
            }
        )
    within = sum(1 for row in rows if row["within_1"])
    mean_overlap = sum(float(row["jaccard"]) for row in rows) / len(rows)
    stable = _stability_ok(within, len(rows), mean_overlap)
    _write_stability(dest, rows, stable=stable, blocked=None)
    summary = {
        "within_1": within,
        "jobs": len(rows),
        "mean_jaccard": mean_overlap,
        "stable": stable,
        "spent_usd": format(spent, "f"),
    }
    print(
        f"gold check within_1={within}/{len(rows)} jaccard={mean_overlap:.3f} stable={stable}",
        flush=True,
    )
    if not stable:
        raise GoldUnstable(
            f"teacher agreed within 1 point on {within}/{len(rows)} "
            f"and mean story overlap was {mean_overlap:.3f}"
        )
    return summary


def evaluate_prompts(
    sample: Path,
    gold: Path,
    versions: Sequence[str],
    reps: int,
    half: str,
    dest: Path,
    *,
    dev_n: int = 60,
) -> dict[str, Any]:
    """Score prompt versions offline. Does not query the database or write fit rows."""
    from jobhunt.fit.optimize import load_gold_for_sample, score_version

    if half not in {"dev", "test", "both"}:
        raise BenchmarkError(f"unknown half {half}")
    payload = load_sample(sample)
    labels = load_gold_for_sample(gold, payload)
    dev_ids, test_ids = split_fit_jobs(
        [int(job["job_id"]) for job in payload["jobs"]], seed=int(payload["seed"]), dev_n=dev_n
    )
    selected = {"dev": dev_ids, "test": test_ids, "both": [*dev_ids, *test_ids]}[half]
    jobs_by_id = {int(job["job_id"]): job for job in payload["jobs"]}
    jobs = [jobs_by_id[job_id] for job_id in selected]
    docs = _sample_docs(payload)
    dest.mkdir(parents=True, exist_ok=True)
    scored = []
    for version in versions:
        if version not in {"v1", "v2", "v3"}:
            raise BenchmarkError(f"unknown prompt version {version}")
        result = score_version(
            docs,
            jobs,
            labels,
            name=version,
            prompt_version=version,
            rubric=None,
            reps=reps,
        )
        scored.append(result)
    report: dict[str, Any] = {
        "half": half,
        "versions": [
            {
                "name": result.name,
                "objective": result.objective_value,
                "precision_at_10": result.report.precision_at_10,
                "spearman": result.report.spearman,
                "cost_usd": format(result.cost_usd, "f"),
            }
            for result in scored
        ],
    }
    _write_json(dest / "prompt-eval.json", report)
    lines = ["# Prompt eval", ""]
    for row in report["versions"]:
        lines.append(
            f"- {row['name']}: objective={row['objective']} "
            f"precision={row['precision_at_10']} spearman={row['spearman']}"
        )
    (dest / "prompt-eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def _stability_ok(within: int, total: int, mean_jaccard: float) -> bool:
    """At least 8 of 10 ratings within a point, and mean story overlap at least 0.5."""
    return within * 10 >= 8 * total and mean_jaccard >= 0.5


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    first, second = set(left), set(right)
    if not first and not second:
        return 1.0
    return len(first & second) / len(first | second)


def _sample_docs(payload: dict[str, Any]) -> list[BragDoc]:
    return [
        BragDoc(id=str(doc["id"]), text=str(doc["text"]))
        for doc in payload["docs"]
        if str(doc["id"]).startswith("BB-")
    ]


def _label_system(docs: Sequence[BragDoc]) -> str:
    lines = [_LABEL_RUBRIC, "Stories:"]
    for doc in docs:
        lines.append(f"id={doc.id}")
        lines.append(doc.text)
    return "\n".join(lines)


def _label_user(job: dict[str, Any], errors: Sequence[str]) -> str:
    lines = [
        f"Title: {job['title']}",
        f"Company: {job['company']}",
        "Description:",
        str(job["description"]),
    ]
    if errors:
        lines.extend(["", "Fix these errors:", *errors])
    return "\n".join(lines)


def _label_job(
    system: str, job: dict[str, Any], doc_ids: set[str]
) -> tuple[_GoldFields, list[Any]]:
    from jobhunt.core import claude as claude_core
    from jobhunt.fit.optimize import TEACHER_MODEL

    errors: list[str] = []
    calls: list[Any] = []
    parsed = _GoldFields(rating=1, docs=[], reason="pending")
    for _attempt in range(4):
        try:
            parsed, meta = claude_core.structured_call(
                model=TEACHER_MODEL,
                system=system,
                user=_label_user(job, errors),
                output=_GoldFields,
                max_tokens=8000,
            )
        except claude_core.ClaudeError as exc:
            raise GoldError(str(exc)) from exc
        calls.append(meta)
        errors = _label_errors(parsed, doc_ids)
        if not errors:
            return parsed, calls
    raise GoldError("; ".join(errors))


def _label_errors(parsed: _GoldFields, doc_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if isinstance(parsed.rating, bool) or not isinstance(parsed.rating, int):
        errors.append("rating is not an integer")
    elif not 1 <= parsed.rating <= 5:
        errors.append(f"rating {parsed.rating} is outside 1 to 5")
    if len(parsed.docs) > 10:
        errors.append("docs has more than 10 stories")
    for doc_id in parsed.docs:
        if doc_id not in doc_ids:
            errors.append(f"docs id {doc_id} is unknown")
    if not str(parsed.reason).strip():
        errors.append("reason is empty")
    return errors


def _label_entry(job_id: int, parsed: _GoldFields, meta: Any) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "rating": int(parsed.rating),
        "docs": [str(doc_id) for doc_id in parsed.docs],
        "reason": str(parsed.reason).strip(),
        "call": {
            "model": meta.model,
            "input_tokens": meta.input_tokens,
            "output_tokens": meta.output_tokens,
            "cache_read_tokens": meta.cache_read_tokens,
            "cache_write_tokens": meta.cache_write_tokens,
            "cost_usd": format(meta.cost_usd, "f"),
        },
    }


def _read_gold(path: Path) -> tuple[str | None, list[dict[str, Any]]]:
    if not path.is_file():
        raise GoldError(f"no gold file at {path}")
    import yaml

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GoldError("gold file must be a mapping")
    entries = payload.get("jobs")
    if not isinstance(entries, list):
        raise GoldError("gold file is missing jobs")
    labeler = payload.get("labeler")
    if labeler is not None and not isinstance(labeler, str):
        raise GoldError("labeler is not a string")
    kept = [item for item in entries if isinstance(item, dict)]
    if len(kept) != len(entries):
        raise GoldError("gold entry is not a mapping")
    return labeler, kept


def _gold_job(item: dict[str, Any], doc_ids: set[str]) -> GoldJob:
    call = item.get("call")
    job_id = item.get("job_id")
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise GoldError("gold entry is missing job_id")
    if not isinstance(call, dict) or "model" not in call or "cost_usd" not in call:
        raise GoldError(f"job {job_id} has no call record")
    for key in _CALL_KEYS:
        value = call.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise GoldError(f"job {job_id} call is missing {key}")
    rating = item.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise GoldError(f"job {job_id} rating is outside 1 to 5")
    docs = item.get("docs") or []
    if not isinstance(docs, list) or not all(isinstance(doc, str) for doc in docs):
        raise GoldError(f"job {job_id} docs are not story ids")
    unknown = [doc for doc in docs if doc not in doc_ids]
    if unknown:
        raise GoldError(f"job {job_id} docs id {unknown[0]} is unknown")
    reason = item.get("reason")
    if not isinstance(reason, str):
        raise GoldError(f"job {job_id} reason is missing")
    return GoldJob(
        job_id=int(job_id),
        rating=rating,
        docs=tuple(str(doc) for doc in docs),
        reason=reason,
        model=str(call["model"]),
        cost_usd=str(call["cost_usd"]),
        input_tokens=int(call["input_tokens"]),
        output_tokens=int(call["output_tokens"]),
        cache_read_tokens=int(call["cache_read_tokens"]),
        cache_write_tokens=int(call["cache_write_tokens"]),
    )


def _labeled_spend(entries: Sequence[dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for item in entries:
        call = item.get("call")
        if isinstance(call, dict) and "cost_usd" in call:
            total += Decimal(str(call["cost_usd"]))
    return total


def _gold_file_spend(path: Path) -> Decimal:
    _labeler, entries = _read_gold(path)
    return _labeled_spend(entries)


def _write_gold(path: Path, entries: Sequence[dict[str, Any]]) -> None:
    import yaml

    from jobhunt.fit.optimize import TEACHER_MODEL

    payload = {"labeler": TEACHER_MODEL, "jobs": list(entries)}
    _write_text(path, yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


def _write_stability(
    dest: Path, rows: Sequence[dict[str, Any]], *, stable: bool, blocked: str | None
) -> None:
    from jobhunt.fit.optimize import TEACHER_MODEL

    within = sum(1 for row in rows if row["within_1"])
    mean_overlap = sum(float(row["jaccard"]) for row in rows) / len(rows) if rows else 0.0
    lines = [
        "# Gold stability",
        "",
        f"Teacher: {TEACHER_MODEL}",
        f"Jobs: {len(rows)}",
        f"Ratings within 1 point: {within}/{len(rows)}",
        f"Mean docs Jaccard: {mean_overlap:.3f}",
        f"Stable: {stable}",
    ]
    if blocked:
        lines.append(f"Blocked: {blocked}")
    lines.extend(
        [
            "",
            "| job_id | rating | relabel | within 1 | jaccard |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['job_id']} | {row['rating']} | {row['relabel']} "
            f"| {row['within_1']} | {float(row['jaccard']):.3f} |"
        )
    lines.append("")
    _write_text(dest / "gold-check.md", "\n".join(lines))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)

"""Check a rendered resume against the shortlist it was built from.

The score and the coverage check use only bullets that cite a shortlist doc.
Filler bullets are measured and reported. They cannot fail the gate.
"""

from dataclasses import dataclass

from jobhunt.fit.base import BragDoc, FitScorer
from jobhunt.fit.select import GAP_THRESHOLD


@dataclass(frozen=True)
class GateResult:
    passed: bool
    skipped: bool
    resume_score: float
    resume_coverage: float
    extra_coverage: float
    lost_aspects: list[str]
    feedback: list[str]


def evaluate(
    model: FitScorer,
    job_description: str,
    resume_json: dict[str, object],
    *,
    shortlist_ids: set[str],
    covered_aspects: list[str],
    baseline_score: float,
    baseline_model_id: str,
) -> GateResult:
    """Score shortlist bullets with the same model that scored the job."""
    if model.model_id != baseline_model_id:
        return GateResult(
            passed=True,
            skipped=True,
            resume_score=0.0,
            resume_coverage=0.0,
            extra_coverage=0.0,
            lost_aspects=[],
            feedback=[],
        )
    shortlist, filler = _split_bullets(resume_json, shortlist_ids)
    if not shortlist:
        missing = ["The resume cites none of the shortlisted brag docs."]
        return GateResult(False, False, 0.0, 0.0, 0.0, list(covered_aspects), missing)

    scored = model.fit(shortlist, job_description)
    extra = model.fit(filler, job_description).coverage if filler else 0.0
    lost = [aspect for aspect in covered_aspects if aspect in scored.gaps]
    score_ok = scored.score + 0.05 >= baseline_score
    passed = score_ok and not lost
    feedback: list[str] = []
    if not score_ok:
        feedback.append(
            f"Resume score {scored.score} is below the shortlist baseline {baseline_score}. "
            "Keep every shortlist story, its numbers, and the job's own words for that requirement."
        )
        weakest = sorted(scored.top_docs, key=lambda match: match.similarity)[:5]
        if weakest:
            joined = "; ".join(f"{match.aspect} ({match.similarity:.2f})" for match in weakest)
            feedback.append(f"Weak matches to rewrite with those words: {joined}")
    feedback.extend(f"Lost requirement: {aspect}" for aspect in lost)
    return GateResult(
        passed=passed,
        skipped=False,
        resume_score=scored.score,
        resume_coverage=scored.coverage,
        extra_coverage=extra,
        lost_aspects=lost,
        feedback=feedback,
    )


def covered_aspects(matches: list[dict[str, object]]) -> list[str]:
    """Requirements the shortlist already covers well enough to keep."""
    seen: list[str] = []
    for match in matches:
        similarity = float(match["similarity"])  # type: ignore[arg-type]
        aspect = str(match["aspect"])
        if similarity >= GAP_THRESHOLD and aspect not in seen:
            seen.append(aspect)
    return seen


def cited_ids(resume_json: dict[str, object]) -> list[str]:
    ids: list[str] = []
    for _text, src in _bullets(resume_json):
        for doc_id in src:
            if doc_id not in ids:
                ids.append(doc_id)
    return ids


def _split_bullets(
    resume_json: dict[str, object], shortlist_ids: set[str]
) -> tuple[list[BragDoc], list[BragDoc]]:
    shortlist: list[BragDoc] = []
    filler: list[BragDoc] = []
    for index, (text, src) in enumerate(_bullets(resume_json)):
        doc = BragDoc(id=src[0] if src else f"bullet-{index}", text=text)
        if shortlist_ids.intersection(src):
            shortlist.append(doc)
        else:
            filler.append(doc)
    return shortlist, filler


def _bullets(resume_json: dict[str, object]) -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    experience = resume_json.get("experience")
    if isinstance(experience, list):
        for job in experience:
            if not isinstance(job, dict):
                continue
            roles = job.get("roles")
            if not isinstance(roles, list):
                continue
            for role in roles:
                if isinstance(role, dict):
                    found.extend(_bullet_list(role.get("bullets")))
    for key in ("projects", "extras"):
        groups = resume_json.get(key)
        if not isinstance(groups, list):
            continue
        for group in groups:
            if isinstance(group, dict):
                found.extend(_bullet_list(group.get("bullets")))
    return found


def _bullet_list(raw: object) -> list[tuple[str, list[str]]]:
    if not isinstance(raw, list):
        return []
    bullets: list[tuple[str, list[str]]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        src = item.get("src")
        if not isinstance(text, str) or not text.strip():
            continue
        ids = [str(doc_id) for doc_id in src] if isinstance(src, list) else []
        bullets.append((text, ids))
    return bullets

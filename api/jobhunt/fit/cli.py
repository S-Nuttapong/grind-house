"""Fit commands: scoring, the background worker, the model cache, and calibration."""

from datetime import UTC, datetime
from typing import Any

import typer
from psycopg import Connection

from jobhunt.fit.base import FitScorer

fit_app = typer.Typer(no_args_is_help=True, help="Job fit scoring.")

# A list annotation makes an inline typer.Option trip ruff B008, so this lives at module scope.
_EVAL_MODELS = typer.Option(None, "--model")


calibrate_app = typer.Typer(no_args_is_help=True, help="Score calibration.")


@calibrate_app.command("sample")
def calibrate_sample(
    n: int = typer.Option(60, "--n"),
    seed: int = typer.Option(20261012, "--seed"),
    mode: str = typer.Option("bank", "--mode"),
    out: str = typer.Option("evals/cache/fit-benchmark", "--out"),
) -> None:
    """Score a stratified sample with the existing Claude scorer and freeze it."""
    from pathlib import Path

    from jobhunt.core.db import tx
    from jobhunt.fit.benchmark import BenchmarkError, execute_sample

    destination = Path(out) / str(seed)
    try:
        with tx() as conn:
            digest = execute_sample(conn, n=n, seed=seed, mode=mode, out=destination)
    except BenchmarkError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"froze {destination}")
    typer.echo(f"raw_sha256 {digest}")


@calibrate_app.command("rescore")
def calibrate_rescore(
    run: str = typer.Option(..., "--run"),
    dest: str = typer.Option(..., "--dest"),
) -> None:
    """Score a frozen sample again and print the replay against its judge files."""
    import json
    from pathlib import Path

    from jobhunt.fit.benchmark import BenchmarkError, replay_report, rescore_frozen

    source = Path(run)
    destination = Path(dest)
    try:
        digest = rescore_frozen(source, destination)
        report = replay_report(destination, reviews=source)
    except BenchmarkError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"froze {destination}")
    typer.echo(f"raw_sha256 {digest}")
    typer.echo(json.dumps(report, indent=2))


@calibrate_app.command("report")
def calibrate_report(run: str = typer.Option(..., "--run")) -> None:
    """Print the frozen sample and each judge. Does not combine their recommendations."""
    from pathlib import Path

    from jobhunt.fit.benchmark import BenchmarkError, render_report

    try:
        typer.echo(render_report(Path(run)), nl=False)
    except BenchmarkError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@fit_app.command("run")
def fit_run(
    mode: str = typer.Option("bank", "--mode"),
    limit: int | None = typer.Option(None, "--limit"),
) -> None:
    """Score open jobs against the brag docs or the selected resume."""
    from jobhunt.composition import COMPOSITION
    from jobhunt.core.db import tx
    from jobhunt.fit.pipeline import FitPipeline
    from jobhunt.fit.runner import run_fit
    from jobhunt.fit.sources import SourceError

    started = datetime.now(UTC)
    model = FitPipeline(COMPOSITION).composition.scorer
    try:
        with tx() as conn:
            result = run_fit(conn, model, mode, limit=limit)
            _remember_cli_run(conn, model.model_id, mode, result, started, error=None)
    except (SourceError, ValueError) as exc:
        _remember_cli_failure(model.model_id, mode, started, str(exc))
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"scored {result['scored']}, skipped {result['skipped']} ({model.model_id})")


def _remember_cli_run(
    conn: Connection[Any],
    model_id: str,
    mode: str,
    result: dict[str, int],
    started: datetime,
    error: str | None,
) -> None:
    from jobhunt.fit import repo as fit_repo

    fit_repo.record_finished_run(
        conn,
        {
            "schedule_id": fit_repo.schedule_id_for_mode(conn, mode),
            "mode": mode,
            "trigger": "manual",
            "model_id": model_id,
            "status": "failed" if error else "ok",
            "scored": result["scored"],
            "skipped": result["skipped"],
            "error": error,
            "idempotency_key": f"cli|{mode}|{started.isoformat()}",
            "started_at": started,
            "finished_at": datetime.now(UTC),
        },
    )


def _remember_cli_failure(model_id: str, mode: str, started: datetime, error: str) -> None:
    from jobhunt.core.db import tx

    with tx() as conn:
        _remember_cli_run(conn, model_id, mode, {"scored": 0, "skipped": 0}, started, error)


@fit_app.command("worker")
def fit_worker_cmd() -> None:
    """Score jobs in the background. Loads the model once and polls every minute."""
    from jobhunt.composition import COMPOSITION
    from jobhunt.fit.pipeline import FitPipeline

    FitPipeline(COMPOSITION).serve()


@fit_app.command("download-model")
def fit_download_model(
    model: str = typer.Option(None, "--model", help="qwen3 or bge."),
) -> None:
    """Cache the embedding model into ./.models for the Docker worker."""
    import os

    os.environ.setdefault("HF_HOME", os.path.join(os.getcwd(), ".models"))
    chosen = model or _matrix_name()
    from jobhunt.fit.matrix import CONFIGS, load_matrix

    if chosen not in CONFIGS:
        known = ", ".join(sorted(CONFIGS))
        typer.echo(f"no weights to cache for {chosen!r}; matrix models: {known}", err=True)
        raise typer.Exit(code=1)
    load_matrix(chosen, os.environ["HF_HOME"])
    typer.echo(f"{chosen} cached in {os.environ['HF_HOME']}")


@fit_app.command("score")
def fit_score(
    job: int = typer.Option(..., "--job"),
    mode: str = typer.Option("bank", "--mode"),
) -> None:
    """Print the fit of one job. For ad-hoc checks; the board reads stored scores."""
    from jobhunt.composition import COMPOSITION
    from jobhunt.core.db import tx
    from jobhunt.fit.calibrate import tier
    from jobhunt.fit.keywords import compare
    from jobhunt.fit.pipeline import FitPipeline
    from jobhunt.fit.sources import SourceError, joined_text, resolve

    model = FitPipeline(COMPOSITION).composition.scorer
    try:
        with tx() as conn:
            _source_hash, docs, _resume_id = resolve(conn, mode, model)
            row = conn.execute(
                "SELECT title, description_md FROM jobs WHERE id = %s", (job,)
            ).fetchone()
    except SourceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if row is None:
        typer.echo(f"no job {job}", err=True)
        raise typer.Exit(code=1)
    description = f"{row[0]}\n{row[1] or ''}"
    result = model.fit(docs, description)
    matched, missing = compare(joined_text(docs), description)
    typer.echo(f"{result.score}% {tier(result.score)}")
    for match in result.top_docs:
        typer.echo(f"  {match.brag_doc_id}  {match.similarity:.2f}  {match.aspect}")
    typer.echo(f"gaps: {'; '.join(result.gaps) or '-'}")
    typer.echo(f"matched: {', '.join(matched) or '-'}")
    typer.echo(f"missing: {', '.join(missing) or '-'}")


@fit_app.command("calibrate")
def fit_calibrate(
    model: str = typer.Option(None, "--model", help="qwen3 or bge."),
) -> None:
    """Print a calibration floor and span from stored raw scores. Does not change the model."""
    from jobhunt.core.db import tx
    from jobhunt.fit.calibrate import suggest_floor_span
    from jobhunt.fit.matrix import CONFIGS

    chosen = model or _matrix_name()
    if chosen not in CONFIGS:
        known = ", ".join(sorted(CONFIGS))
        typer.echo(f"unknown fit model {chosen!r}; known: {known}", err=True)
        raise typer.Exit(code=1)
    model_id = CONFIGS[chosen].model_id
    with tx() as conn:
        raw_scores = [
            float(value)
            for (value,) in conn.execute(
                "SELECT raw FROM job_fits WHERE model_id = %s", (model_id,)
            ).fetchall()
            if isinstance(value, int | float)
        ]
    suggestion = suggest_floor_span(raw_scores)
    typer.echo(f"model {model_id}")
    typer.echo(f"raw scores: {len(raw_scores)}")
    if suggestion is None:
        typer.echo(
            "not enough variation to suggest a floor and span (need at least 2 different scores)"
        )
        raise typer.Exit(code=1)
    floor, span = suggestion
    typer.echo(f"5th percentile (floor): {floor:.4f}")
    typer.echo(f"span to the 95th percentile: {span:.4f}")


@fit_app.command("eval")
def fit_eval(
    labels: str = typer.Option(..., "--labels", help="Private YAML of job ratings. Not committed."),
    model: list[str] | None = _EVAL_MODELS,
    reps: int = typer.Option(1, "--reps", help="Repeated scores for retest sd and ICC."),
) -> None:
    """Score labeled jobs with eval_fit. Loads each named model, or the composition scorer."""
    from pathlib import Path

    import yaml

    from jobhunt.core.db import tx
    from jobhunt.fit.eval import FitLabel, eval_fit
    from jobhunt.fit.sources import SourceError, resolve

    path = Path(labels)
    if not path.is_file():
        typer.echo(f"no label file at {path}", err=True)
        raise typer.Exit(code=1)
    rows = _label_rows(yaml.safe_load(path.read_text()))
    chosen = model or [_matrix_name()]
    failed = False
    for name in chosen:
        try:
            scorer = _named_scorer(name)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            failed = True
            continue
        try:
            with tx() as conn:
                _source_hash, docs, _resume_id = resolve(conn, "bank", scorer)
                found = _job_texts(conn, [row["job_id"] for row in rows])
        except SourceError as exc:
            typer.echo(f"{name}: {exc}", err=True)
            failed = True
            continue
        present = [row for row in rows if row["job_id"] in found]
        missing = len(rows) - len(present)
        if missing:
            typer.echo(f"{name}: skipped {missing} unknown job ids", err=True)
        if not present:
            typer.echo(f"{scorer.model_id}: no labeled jobs in the database")
            failed = True
            continue
        fit_labels = [
            FitLabel(
                description=found[row["job_id"]],
                rating=float(row["rating"]),
                docs=tuple(row["docs"]),
            )
            for row in present
        ]
        report = eval_fit(scorer, docs, fit_labels, reps)
        rho_text = "n/a" if report.spearman is None else f"{report.spearman:.3f}"
        labeled_docs = sum(1 for row in present if row["docs"])
        if report.hit_at_10 is None:
            hit_text = "n/a"
        else:
            hit_text = f"{report.hit_at_10:.3f} (n={labeled_docs})"
        typer.echo(f"{scorer.model_id}")
        typer.echo(f"  spearman: {rho_text} (n={len(present)})")
        typer.echo(f"  hit@10: {hit_text}")
        if report.kappa is not None:
            typer.echo(f"  kappa: {report.kappa:.3f}")
        if report.retest_sd is not None:
            typer.echo(f"  retest_sd: {report.retest_sd:.3f}")
        if report.order_delta is not None:
            typer.echo(f"  order_delta: {report.order_delta:.3f}")
    if failed:
        raise typer.Exit(code=1)


def _matrix_name() -> str:
    from jobhunt.composition import COMPOSITION

    name = getattr(COMPOSITION.scorer, "name", None)
    if not isinstance(name, str):
        raise ValueError("the composition scorer is not a matrix model")
    return name


def _named_scorer(name: str) -> FitScorer:
    from jobhunt.composition import COMPOSITION, require_on_machine
    from jobhunt.fit.fake import FakeFitScorer
    from jobhunt.fit.matrix import CONFIGS, MatrixFitScorer

    if name == getattr(COMPOSITION.scorer, "name", None):
        require_on_machine(COMPOSITION.scorer, "fit scorer")
        return COMPOSITION.scorer
    if name == "fake":
        return FakeFitScorer()
    if name in CONFIGS:
        return MatrixFitScorer(name)
    known = ", ".join(["fake", *sorted(CONFIGS)])
    raise ValueError(f"unknown fit model {name!r}; known: {known}")


def _label_rows(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not payload:
        typer.echo("labels must be a non-empty list of {job_id, rating, docs?}", err=True)
        raise typer.Exit(code=1)
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or "job_id" not in item or "rating" not in item:
            typer.echo("each label needs job_id and rating", err=True)
            raise typer.Exit(code=1)
        rating = int(item["rating"])
        if rating < 1 or rating > 5:
            typer.echo(f"rating {rating} is outside 1–5", err=True)
            raise typer.Exit(code=1)
        docs = item.get("docs") or []
        if not isinstance(docs, list) or not all(isinstance(doc, str) for doc in docs):
            typer.echo("docs must be a list of brag doc ids", err=True)
            raise typer.Exit(code=1)
        rows.append(
            {
                "job_id": int(item["job_id"]),
                "rating": rating,
                "docs": [str(doc) for doc in docs],
            }
        )
    return rows


@fit_app.command("gold-sample")
def gold_sample(
    out: str = typer.Option("evals/cache/fit-benchmark/roles-100", "--out"),
    n: int = typer.Option(100, "--n"),
    seed: int = typer.Option(20261012, "--seed"),
    exclude: str | None = typer.Option(None, "--exclude"),
) -> None:
    """Draw role-grid jobs into a frozen sample. Reads the database, writes no fits."""
    import os
    from pathlib import Path

    from jobhunt.core.db import close_pool, tx
    from jobhunt.fit.benchmark import BenchmarkError
    from jobhunt.fit.roles import prepare_sample

    os.environ["DATABASE_URL"] = (
        "postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable"
    )
    _load_env_value("VAULT_BANK_PATH")
    close_pool()
    destination = Path(out)
    try:
        with tx() as conn:
            path = prepare_sample(conn, destination, n=n, seed=seed, exclude=_exclude_ids(exclude))
    except BenchmarkError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote {path}")


@fit_app.command("gold-label")
def gold_label(
    sample: str = typer.Option("evals/cache/fit-benchmark/roles-100/sample.json", "--sample"),
    dest: str = typer.Option("evals/gold/fit-roles-100.yaml", "--dest"),
) -> None:
    """Label the frozen sample with the teacher model. Resumes a partial file."""
    from pathlib import Path

    from jobhunt.fit.optimize import TeacherModelRejected
    from jobhunt.fit.roles import GoldBudget, GoldError, label_fit_gold

    _prepare_offsite()
    try:
        path = label_fit_gold(Path(sample), Path(dest))
    except (GoldError, GoldBudget, TeacherModelRejected) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote {path}")


@fit_app.command("gold-check")
def gold_check(
    sample: str = typer.Option("evals/cache/fit-benchmark/roles-100/sample.json", "--sample"),
    gold: str = typer.Option("evals/gold/fit-roles-100.yaml", "--gold"),
    dest: str = typer.Option("evals/cache/fit-benchmark/roles-100", "--dest"),
) -> None:
    """Relabel 10 jobs. Exit 2 when the teacher does not agree with itself."""
    from pathlib import Path

    from jobhunt.fit.roles import GoldError, GoldUnstable, check_label_stability

    _prepare_offsite()
    try:
        summary = check_label_stability(Path(sample), Path(gold), Path(dest))
    except GoldUnstable as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    except GoldError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"stable within_1={summary['within_1']}/{summary['jobs']} "
        f"jaccard={summary['mean_jaccard']:.3f} spent_usd={summary['spent_usd']}"
    )


@fit_app.command("prompt-optimize")
def prompt_optimize(
    sample: str = typer.Option("evals/cache/fit-benchmark/roles-100/sample.json", "--sample"),
    gold: str = typer.Option("evals/gold/fit-roles-100.yaml", "--gold"),
    dest: str = typer.Option("evals/cache/fit-benchmark/roles-100/optimize", "--dest"),
    loop_only: bool = typer.Option(False, "--loop-only"),
    decide_only: bool = typer.Option(False, "--decide-only"),
    test_sample: str | None = typer.Option(None, "--test-sample"),
    test_gold: str | None = typer.Option(None, "--test-gold"),
) -> None:
    """Revise the Haiku rubric on the dev half, then test it once."""
    from pathlib import Path

    from jobhunt.fit.optimize import TeacherModelRejected, decide_prompt, optimize_prompt
    from jobhunt.fit.roles import GoldError

    _prepare_offsite()
    sample_path = Path(sample)
    gold_path = Path(gold)
    out = Path(dest)
    fresh_sample = None if test_sample is None else Path(test_sample)
    fresh_gold = None if test_gold is None else Path(test_gold)
    try:
        if not decide_only:
            loop = optimize_prompt(sample_path, gold_path, out)
            typer.echo(
                f"loop stopped={loop['stopped']} best={loop['best']} "
                f"spent_usd={loop['spent_usd']} scored_rounds={loop['scored_rounds']}"
            )
        if loop_only:
            return
        decision = decide_prompt(
            sample_path,
            gold_path,
            out,
            test_sample=fresh_sample,
            test_gold=fresh_gold,
        )
    except (GoldError, TeacherModelRejected, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"shipped={decision['shipped']} report={decision['report']}")
    if decision["gates"]:
        typer.echo("gates: " + "; ".join(decision["gates"]))


def _exclude_ids(path: str | None) -> set[int]:
    import json
    from pathlib import Path

    if path is None:
        return set()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(job["job_id"]) for job in payload["jobs"]}


def _prepare_offsite() -> None:
    """Allow the teacher and student calls. Load the API key without printing it."""
    import os
    from pathlib import Path

    os.environ["JOBHUNT_ALLOW_OFFSITE"] = "1"
    root = Path(__file__).resolve().parents[3]
    cert = root / ".certs" / "ca-bundle.pem"
    os.environ.setdefault("SSL_CERT_FILE", str(cert))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", str(cert))
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    if _load_env_value("ANTHROPIC_API_KEY"):
        return
    typer.echo("ANTHROPIC_API_KEY is not set", err=True)
    raise typer.Exit(code=1)


def _load_env_value(name: str) -> bool:
    """Set one variable from the repo .env when it is missing. Never prints the value."""
    import os
    from pathlib import Path

    if os.environ.get(name):
        return True
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.is_file():
        return False
    prefix = f"{name}="
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith(prefix):
            continue
        value = line.split("=", 1)[1].strip().strip('"').strip("'")
        if value:
            os.environ[name] = value
            return True
    return False


def _job_texts(conn: Connection[Any], job_ids: list[int]) -> dict[int, str]:
    if not job_ids:
        return {}
    cursor = conn.execute(
        "SELECT id, title, description_md FROM jobs WHERE id = ANY(%s)",
        (job_ids,),
    )
    return {int(row[0]): f"{row[1]}\n{row[2] or ''}" for row in cursor.fetchall()}

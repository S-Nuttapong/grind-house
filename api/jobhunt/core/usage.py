"""One row per Claude call. Prompt text is never stored."""

from decimal import Decimal
from typing import Any

from jobhunt.core.db import tx
from jobhunt.core.log import get_logger

log = get_logger("usage")


def record_model_call(
    *,
    purpose: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_usd: Decimal | str | float = 0,
    job_id: int | None = None,
    success: bool = True,
    error: str | None = None,
    run_id: int | None = None,
    attempt: int = 1,
    agent_id: str = "claude",
    duration_ms: int = 0,
) -> None:
    """Insert a usage row on its own connection so a scoring transaction can still roll back."""
    try:
        with tx() as conn:
            conn.execute(
                """
                INSERT INTO agent_usage (
                    run_kind, run_id, attempt, agent_id, model,
                    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    num_turns, duration_ms, cost_usd, cost_source,
                    purpose, job_id, success, error
                )
                VALUES (
                    %(purpose)s, %(run_id)s, %(attempt)s, %(agent_id)s, %(model)s,
                    %(input_tokens)s, %(output_tokens)s, %(cache_read_tokens)s, %(cache_write_tokens)s,
                    0, %(duration_ms)s, %(cost_usd)s, 'computed',
                    %(purpose)s, %(job_id)s, %(success)s, %(error)s
                )
                """,
                {
                    "purpose": purpose,
                    "run_id": run_id,
                    "attempt": attempt,
                    "agent_id": agent_id,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_write_tokens": cache_write_tokens,
                    "duration_ms": duration_ms,
                    "cost_usd": cost_usd,
                    "job_id": job_id,
                    "success": success,
                    "error": None if not error else str(error)[:500],
                },
            )
    except Exception:
        log.warning("could not record model usage", exc_info=True)


def from_meta(purpose: str, meta: Any, *, job_id: int | None, success: bool, error: str | None = None) -> None:
    record_model_call(
        purpose=purpose,
        model=str(meta.model),
        input_tokens=int(meta.input_tokens),
        output_tokens=int(meta.output_tokens),
        cache_read_tokens=int(meta.cache_read_tokens),
        cache_write_tokens=int(meta.cache_write_tokens),
        cost_usd=meta.cost_usd,
        job_id=job_id,
        success=success,
        error=error,
    )

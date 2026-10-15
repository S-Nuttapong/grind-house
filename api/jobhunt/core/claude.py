"""Claude client for structured completions. Tokens and cost are logged. Prompt text is not."""

from decimal import Decimal
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError

from jobhunt.core.llm import CallMeta
from jobhunt.core.llm import LLMError as ClaudeError
from jobhunt.core.llm import LLMInvalid as ClaudeInvalid
from jobhunt.core.llm import LLMRefusal as ClaudeRefusal
from jobhunt.core.llm import LLMTruncated as ClaudeTruncated
from jobhunt.core.log import get_logger

__all__ = [
    "CallMeta",
    "ClaudeError",
    "ClaudeInvalid",
    "ClaudeLLM",
    "ClaudeRefusal",
    "ClaudeTruncated",
    "structured_call",
]

log = get_logger("claude")

# Per million tokens: (input, output, 5-minute cache write, cache read).
# The cutoff is prompt tokens (input + cache read + cache write).
# https://platform.claude.com/docs/en/about-claude/pricing
_HAIKU = "claude-haiku-5-5"
_OPUS = "claude-opus-5-5"
_SHORT_LIMIT = 100_000
_HAIKU_SHORT = (Decimal("0.10"), Decimal("0.50"), Decimal("0.125"), Decimal("0.01"))
_HAIKU_LONG = (Decimal("0.50"), Decimal("2.50"), Decimal("0.625"), Decimal("0.05"))
_OPUS_SHORT = (Decimal("4"), Decimal("20"), Decimal("5"), Decimal("0.40"))
_Rate = tuple[Decimal, Decimal, Decimal, Decimal]
_PRICES: dict[str, tuple[_Rate, _Rate | None]] = {
    _HAIKU: (_HAIKU_SHORT, _HAIKU_LONG),
    _OPUS: (_OPUS_SHORT, None),
}
_MILLION = Decimal(1_000_000)


class ClaudeLLM:
    """StructuredLLM client. Prompt caching stays here; other providers do not see it."""

    sends_data_offsite = True

    def __init__(self, model: str = _HAIKU) -> None:
        self.model_id = model

    def complete[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        output: type[T],
        max_tokens: int,
    ) -> tuple[T, CallMeta]:
        return structured_call(
            model=self.model_id,
            system=system,
            user=user,
            output=output,
            max_tokens=max_tokens,
        )


class _Parser(Protocol):
    def parse(self, **kwargs: Any) -> Any: ...


class _Messages(Protocol):
    @property
    def messages(self) -> _Parser: ...


def structured_call[T: BaseModel](
    *,
    model: str,
    system: str,
    user: str,
    output: type[T],
    max_tokens: int,
    client: _Messages | None = None,
) -> tuple[T, CallMeta]:
    """Parse one reply into `output`. The system block is marked for prompt caching."""
    api = client or _client()
    tokens = max_tokens
    schema_retried = False
    truncated_retried = False
    calls: list[CallMeta] = []
    while True:
        try:
            message = _parse(api, model, tokens, system, user, output)
        except ValidationError:
            if schema_retried:
                raise ClaudeInvalid("reply did not match the schema", calls) from None
            schema_retried = True
            continue
        meta = _meta(message, model)
        calls.append(meta)
        _log(meta)
        if message.stop_reason == "refusal":
            raise ClaudeRefusal("model refused", calls)
        if message.stop_reason == "max_tokens":
            if not truncated_retried:
                truncated_retried = True
                tokens *= 2
                continue
            raise ClaudeTruncated(f"reply hit max_tokens at {tokens} tokens", calls)
        parsed = message.parsed_output
        if not isinstance(parsed, output):
            if schema_retried:
                raise ClaudeInvalid("reply did not match the schema", calls)
            schema_retried = True
            continue
        return parsed, meta


def _parse(api: _Messages, model: str, tokens: int, system: str, user: str, output: type[BaseModel]) -> Any:
    try:
        return api.messages.parse(
            model=model,
            max_tokens=tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
            output_format=output,
        )
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        text = str(exc).lower()
        limited = status == 429 or "rate limit" in text or "rate_limit" in text or "usage limit" in text
        if limited:
            from jobhunt.core.llm import LLMRateLimited

            raise LLMRateLimited(str(exc)) from exc
        raise


def _client() -> _Messages:
    import anthropic

    # 429 is not retried here. The fit run stops and is marked partial.
    return cast(_Messages, anthropic.Anthropic(max_retries=0))


def _meta(message: Any, model: str) -> CallMeta:
    usage = message.usage
    input_tokens = int(usage.input_tokens or 0)
    output_tokens = int(usage.output_tokens or 0)
    cache_read = int(usage.cache_read_input_tokens or 0)
    cache_write = int(usage.cache_creation_input_tokens or 0)
    return CallMeta(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=_cost(model, input_tokens, output_tokens, cache_read, cache_write),
    )


def _cost(
    model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int
) -> Decimal:
    """Dollar cost for one call. An unknown model raises instead of using Haiku rates."""
    rates = _PRICES.get(model)
    if rates is None:
        raise ValueError(f"no price for model {model}")
    short, long = rates
    prompt = input_tokens + cache_read + cache_write
    if prompt > _SHORT_LIMIT:
        if long is None:
            raise ValueError(f"no long-context price for model {model}")
        input_rate, output_rate, write_rate, read_rate = long
    else:
        input_rate, output_rate, write_rate, read_rate = short
    spent = (
        Decimal(input_tokens) * input_rate
        + Decimal(output_tokens) * output_rate
        + Decimal(cache_write) * write_rate
        + Decimal(cache_read) * read_rate
    )
    return (spent / _MILLION).quantize(Decimal("0.00000001"))


def _log(meta: CallMeta) -> None:
    log.info(
        "claude model=%s input=%s output=%s cache_read=%s cache_write=%s cost_usd=%s",
        meta.model,
        meta.input_tokens,
        meta.output_tokens,
        meta.cache_read_tokens,
        meta.cache_write_tokens,
        meta.cost_usd,
    )

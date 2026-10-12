"""One structured call to Claude. Tokens and cost are logged. Prompt text is not."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError

from jobhunt.core.log import get_logger

log = get_logger("claude")

# Haiku 5.5, global routing, prompts up to 100k tokens.
# https://platform.claude.com/docs/en/about-claude/pricing
_SHORT = (100_000, Decimal("0.10"), Decimal("0.50"), Decimal("0.125"), Decimal("0.01"))
_LONG = (100_000, Decimal("0.50"), Decimal("2.50"), Decimal("0.625"), Decimal("0.05"))
_MILLION = Decimal(1_000_000)


class ClaudeError(Exception):
    """The model did not return a usable structured result."""


class ClaudeRefusal(ClaudeError):
    """The model refused. Not retried."""


class ClaudeTruncated(ClaudeError):
    """The reply hit max_tokens twice."""


class ClaudeInvalid(ClaudeError):
    """The reply did not match the schema after one retry."""


@dataclass(frozen=True)
class CallMeta:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: Decimal


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
    while True:
        try:
            message = api.messages.parse(
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
        except ValidationError:
            if schema_retried:
                raise ClaudeInvalid() from None
            schema_retried = True
            continue
        meta = _meta(message, model)
        _log(meta)
        if message.stop_reason == "refusal":
            raise ClaudeRefusal()
        if message.stop_reason == "max_tokens":
            if not truncated_retried:
                truncated_retried = True
                tokens *= 2
                continue
            raise ClaudeTruncated()
        parsed = message.parsed_output
        if not isinstance(parsed, output):
            if schema_retried:
                raise ClaudeInvalid()
            schema_retried = True
            continue
        return parsed, meta


def _client() -> _Messages:
    import anthropic

    return cast(_Messages, anthropic.Anthropic(max_retries=3))


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
        cost_usd=_cost(input_tokens, output_tokens, cache_read, cache_write),
    )


def _cost(input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> Decimal:
    prompt = input_tokens + cache_read + cache_write
    _limit, input_rate, output_rate, write_rate, read_rate = _LONG if prompt > _SHORT[0] else _SHORT
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

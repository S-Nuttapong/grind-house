"""Token prices used when the SDK does not report a dollar cost.

https://platform.claude.com/docs/en/about-claude/pricing
Haiku prompts over 100K input tokens use the long-context rates.
Opus 5.5 has no long-context price, so a prompt that large raises.
"""

from decimal import Decimal

_MILLION = Decimal(1_000_000)
_LONG = 100_000
_OPUS = "claude-opus-5-5"

# (input, output, 5-minute cache write, cache read) per million tokens.
_HAIKU_SHORT = (Decimal("0.10"), Decimal("0.50"), Decimal("0.125"), Decimal("0.01"))
_HAIKU_LONG = (Decimal("0.50"), Decimal("2.50"), Decimal("0.625"), Decimal("0.05"))
_OPUS_SHORT = (Decimal("4"), Decimal("20"), Decimal("5"), Decimal("0.40"))
_Rate = tuple[Decimal, Decimal, Decimal, Decimal]


def estimate(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> Decimal:
    """Dollar cost. Unknown models use the Haiku 5.5 table."""
    prompt = input_tokens + cache_read_tokens + cache_write_tokens
    rates = _rates(model, prompt)
    input_rate, output_rate, write_rate, read_rate = rates
    total = (
        Decimal(input_tokens) * input_rate
        + Decimal(output_tokens) * output_rate
        + Decimal(cache_write_tokens) * write_rate
        + Decimal(cache_read_tokens) * read_rate
    )
    return (total / _MILLION).quantize(Decimal("0.000001"))


def _rates(model: str, prompt_tokens: int) -> _Rate:
    if model == _OPUS:
        if prompt_tokens > _LONG:
            raise ValueError(f"{_OPUS} has no long-context price")
        return _OPUS_SHORT
    return _HAIKU_LONG if prompt_tokens > _LONG else _HAIKU_SHORT

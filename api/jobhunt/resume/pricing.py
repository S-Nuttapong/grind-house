"""Haiku 5.5 prices, used when the SDK does not report a dollar cost.

https://platform.claude.com/docs/en/models/haiku-5-5/overview
Prompts over 100K input tokens use the long-context rates.
"""

from decimal import Decimal

_MILLION = Decimal(1_000_000)
_LONG = 100_000

# (input, output, 5-minute cache write, cache read) per million tokens.
_SHORT = (Decimal("0.10"), Decimal("0.50"), Decimal("0.125"), Decimal("0.01"))
_LONG_RATES = (Decimal("0.50"), Decimal("2.50"), Decimal("0.625"), Decimal("0.05"))


def estimate(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> Decimal:
    """Dollar cost. Unknown models use the Haiku 5.5 table, which is the default."""
    _ = model
    prompt = input_tokens + cache_read_tokens + cache_write_tokens
    rates = _LONG_RATES if prompt > _LONG else _SHORT
    input_rate, output_rate, write_rate, read_rate = rates
    total = (
        Decimal(input_tokens) * input_rate
        + Decimal(output_tokens) * output_rate
        + Decimal(cache_write_tokens) * write_rate
        + Decimal(cache_read_tokens) * read_rate
    )
    return (total / _MILLION).quantize(Decimal("0.000001"))

"""Provider-neutral structured completion. Clients live next to their SDKs."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class CallMeta:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: Decimal


class LLMRateLimited(Exception):
    """429 or a plan limit. Callers stop. They do not retry."""


class LLMError(Exception):
    """The model did not return a usable structured result."""

    def __init__(self, message: str, calls: list[CallMeta] | None = None) -> None:
        super().__init__(message)
        self.calls = list(calls or [])


class LLMRefusal(LLMError):
    """The model refused. Not retried."""


class LLMTruncated(LLMError):
    """The reply hit max_tokens twice."""


class LLMInvalid(LLMError):
    """The reply did not match the schema after one retry."""


class StructuredLLM(Protocol):
    """One completion into a pydantic model.

    Every client retries a schema mismatch once and a truncated reply once
    (with the token cap doubled), and does not retry a refusal.
    """

    model_id: str
    sends_data_offsite: bool

    def complete[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        output: type[T],
        max_tokens: int,
    ) -> tuple[T, CallMeta]: ...

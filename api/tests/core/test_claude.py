"""structured_call retries. No network."""

from decimal import Decimal
from typing import Any

import pytest
from jobhunt.core.claude import (
    ClaudeInvalid,
    ClaudeRefusal,
    ClaudeTruncated,
    structured_call,
)
from pydantic import BaseModel, ValidationError


class _Out(BaseModel):
    name: str


class _Usage:
    input_tokens = 100
    output_tokens = 20
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Message:
    def __init__(self, stop_reason: str, parsed: _Out | None) -> None:
        self.stop_reason = stop_reason
        self.parsed_output = parsed
        self.usage = _Usage()


class _Messages:
    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> _Message:
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _Client:
    def __init__(self, script: list[Any]) -> None:
        self.messages = _Messages(script)


def test_refusal_is_not_retried() -> None:
    client = _Client([_Message("refusal", None)])
    with pytest.raises(ClaudeRefusal):
        structured_call(
            model="claude-haiku-5-5",
            system="rules",
            user="secret posting",
            output=_Out,
            max_tokens=100,
            client=client,
        )
    assert len(client.messages.calls) == 1


def test_max_tokens_retries_once_at_double() -> None:
    client = _Client([_Message("max_tokens", None), _Message("max_tokens", None)])
    with pytest.raises(ClaudeTruncated):
        structured_call(
            model="claude-haiku-5-5",
            system="rules",
            user="posting",
            output=_Out,
            max_tokens=100,
            client=client,
        )
    assert [call["max_tokens"] for call in client.messages.calls] == [100, 200]


def _invalid() -> ValidationError:
    return ValidationError.from_exception_data("out", [])


def test_schema_error_retries_once() -> None:
    client = _Client([_invalid(), _Message("end_turn", _Out(name="ok"))])
    parsed, meta = structured_call(
        model="claude-haiku-5-5",
        system="rules",
        user="posting",
        output=_Out,
        max_tokens=100,
        client=client,
    )
    assert parsed.name == "ok"
    assert meta.cost_usd == Decimal("0.00002000")
    assert len(client.messages.calls) == 2


def test_a_second_schema_error_is_invalid() -> None:
    client = _Client([_invalid(), _invalid()])
    with pytest.raises(ClaudeInvalid):
        structured_call(
            model="claude-haiku-5-5",
            system="rules",
            user="posting",
            output=_Out,
            max_tokens=100,
            client=client,
        )


def test_system_block_is_cached_and_the_prompt_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _Client([_Message("end_turn", _Out(name="ok"))])
    structured_call(
        model="claude-haiku-5-5",
        system="rules",
        user="secret posting",
        output=_Out,
        max_tokens=100,
        client=client,
    )
    system = client.messages.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "secret posting" not in caplog.text

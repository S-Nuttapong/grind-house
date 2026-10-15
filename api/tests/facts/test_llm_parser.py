"""The job-facts prompt is provider-neutral and any StructuredLLM can run it."""

from decimal import Decimal

import pytest
from jobhunt.composition import COMPOSITION, job_facts_llm
from jobhunt.core.llm import CallMeta
from jobhunt.facts.base import PostingInput
from jobhunt.facts.extraction import JOB_FACTS, ParsedFields
from jobhunt.facts.llm_parser import LLMParser

_BOARDS = ("seek", "greenhouse", "linkedin", "indeed", "lever", "ashby", "jobsdb")


class _FakeLLM:
    model_id = "fake-model"
    sends_data_offsite = False

    def __init__(self) -> None:
        self.system = ""
        self.user = ""

    def complete(self, *, system: str, user: str, output: type[ParsedFields], max_tokens: int):
        del max_tokens
        self.system = system
        self.user = user
        parsed = output(
            role="unknown",
            level="unknown",
            workplace="unknown",
            job_type="unknown",
            country="unknown",
            city="",
            currency="unknown",
            interval="unknown",
            minimum="",
            maximum="",
            posted="unknown",
            evidence_role="",
            evidence_level="",
            evidence_workplace="",
            evidence_job_type="",
            evidence_location="",
            evidence_pay="",
            evidence_posted="",
        )
        return parsed, _meta()


def test_prompt_is_versioned_and_names_no_board() -> None:
    assert JOB_FACTS.version == "v3"
    lowered = JOB_FACTS.system.lower()
    for board in _BOARDS:
        assert board not in lowered
    assert "฿" not in JOB_FACTS.system
    assert "thb" not in lowered
    assert "yearly" in lowered and "hourly" in lowered and "monthly" in lowered
    assert "respond in json" not in lowered


def test_schema_is_strict_and_portable() -> None:
    schema = ParsedFields.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    for prop in schema["properties"].values():
        assert "default" not in prop


def test_any_client_can_run_the_spec() -> None:
    client = _FakeLLM()
    parser = LLMParser(client)
    assert parser.parser_id == "fake-model/v3"
    assert parser.sends_data_offsite is False
    detail = parser.parse(PostingInput(title="Backend Engineer", description_md="Build APIs."))
    assert detail.role is None
    assert client.system == JOB_FACTS.system
    assert "Backend Engineer" in client.user


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown llm"):
        job_facts_llm("openai")


def test_default_parser_id_stays_on_v1() -> None:
    assert LLMParser().parser_id == "claude-haiku-5-5/v3"


def test_live_composition_runs_the_v3_prompt_on_haiku() -> None:
    parser = COMPOSITION.parser
    assert isinstance(parser, LLMParser)
    assert parser.llm.model_id == "claude-haiku-5-5"
    assert parser.parser_id.endswith("/v3")


def _meta() -> CallMeta:
    return CallMeta(
        model="fake-model",
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=Decimal("0"),
    )

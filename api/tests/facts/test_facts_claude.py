"""Claude parser schema and mapping. No network."""

from jobhunt.facts.extraction import JOB_FACTS, ParsedFields, detail_from_parsed
from jobhunt.scrape.normalize.role import role_ids


def test_schema_requires_every_field_and_has_no_reasoning() -> None:
    schema = ParsedFields.model_json_schema()
    assert "reasoning" not in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]["role"]["enum"]) == role_ids() | {"unknown"}
    assert "unknown" in schema["properties"]["level"]["enum"]


def test_level_is_not_taken_from_years_alone() -> None:
    assert "years of experience" in JOB_FACTS.system
    assert "When in doubt, unknown" in JOB_FACTS.system


def test_unknown_fields_stay_empty() -> None:
    parsed = ParsedFields(
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
    detail = detail_from_parsed(parsed, "claude-haiku-5-5/v1")
    assert detail.role is None
    assert detail.level is None
    assert detail.pay is None
    assert detail.locations is None
    assert detail.posted is None


def test_a_stated_role_and_level_are_kept() -> None:
    parsed = ParsedFields(
        role="software",
        level="senior",
        workplace="remote",
        job_type="fulltime",
        country="US",
        city="Austin",
        currency="USD",
        interval="yearly",
        minimum="100000",
        maximum="120000",
        posted="2026-10-01",
        evidence_role="software engineer",
        evidence_level="Senior",
        evidence_workplace="Remote",
        evidence_job_type="Full-time",
        evidence_location="Austin, US",
        evidence_pay="100000",
        evidence_posted="2026-10-01",
    )
    detail = detail_from_parsed(parsed, "claude-haiku-5-5/v1")
    assert detail.role is not None and detail.role.value == "software"
    assert detail.level is not None and detail.level.value == "senior"
    assert detail.locations is not None and detail.locations.value[0].country == "US"
    assert detail.pay is not None and detail.pay.value.minimum is not None
    assert detail.posted is not None and detail.posted.value.isoformat() == "2026-10-01"
    assert detail.role.parser_id == "claude-haiku-5-5/v1"

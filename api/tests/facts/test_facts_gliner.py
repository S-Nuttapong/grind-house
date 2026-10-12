"""GLiNER contract. Marked slow because it loads the local model."""

import pytest
from jobhunt.facts.gliner import GlinerParser

pytestmark = pytest.mark.slow


def test_gliner_empty_and_evidence() -> None:
    parser = GlinerParser()
    assert parser.parse("").pay is None
    text = (
        "The base salary is $120,000 - $150,000 per year in Austin, Texas. "
        "Employment is full-time and hybrid."
    )
    detail = parser.parse(text)
    for fact in (detail.pay, detail.job_type, detail.workplace, detail.locations):
        if fact is None:
            continue
        assert fact.evidence
        assert fact.evidence in text
        assert 0 <= fact.confidence <= 1

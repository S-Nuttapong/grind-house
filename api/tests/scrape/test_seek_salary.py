"""SEEK salary labels are text for the parser, not a parsed pay fact."""

from jobhunt.scrape.sources.seek import SeekSource

_SOURCE = SeekSource()


def test_salary_label_is_appended_and_not_parsed_here() -> None:
    detail = _SOURCE.payload_facts({"country": "th", "salary": "฿40,000 per month"})
    assert detail.pay is None
    assert detail.locations is not None
    assert detail.locations.value[0].country == "TH"
    text = _SOURCE.augment_text({"salary": "฿55,000 – ฿80,000 per month"}, "Build APIs.")
    assert "Salary: ฿55,000 – ฿80,000 per month" in text


def test_empty_salary_label_leaves_the_description_unchanged() -> None:
    detail = _SOURCE.payload_facts({"country": "TH", "salary": ""})
    assert detail.pay is None
    assert detail.locations is not None
    assert _SOURCE.augment_text({"salary": ""}, "Build APIs.") == "Build APIs."

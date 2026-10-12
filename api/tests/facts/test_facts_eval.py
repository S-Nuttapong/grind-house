"""Parser eval counts. No network and no database."""

from jobhunt.facts.base import JobDetail, PostingInput, TextFact
from jobhunt.facts.eval import ParserCase, eval_parser, parser_gates


class _Oracle:
    parser_id = "api:oracle"

    def parse(self, posting: PostingInput) -> JobDetail:
        if "software" in posting.title:
            return JobDetail(
                role=TextFact(
                    value="software", confidence=1, evidence=posting.title, parser_id="api:oracle"
                )
            )
        return JobDetail()


class _Empty:
    parser_id = "empty"

    def parse(self, posting: PostingInput) -> JobDetail:
        del posting
        return JobDetail()


class _Broken:
    parser_id = "broken"

    def parse(self, posting: PostingInput) -> JobDetail:
        del posting
        raise RuntimeError("schema")


def _cases() -> list[ParserCase]:
    return [
        ParserCase(
            case_id="1",
            posting=PostingInput(title="software engineer", description_md="Build services."),
            expected=JobDetail(
                role=TextFact(
                    value="software", confidence=1, evidence="software engineer", parser_id="gold"
                )
            ),
        )
    ]


def test_an_oracle_passes_and_an_empty_parser_scores_nothing() -> None:
    oracle = eval_parser(_Oracle(), _cases(), cache_dir=None)
    assert oracle.precision == 1
    assert oracle.recall == 1
    assert oracle.hallucination == 0
    assert parser_gates(oracle) == []
    empty = eval_parser(_Empty(), _cases(), cache_dir=None)
    assert empty.recall == 0
    assert empty.precision is None
    assert parser_gates(empty)


def test_a_parser_error_is_not_schema_valid() -> None:
    report = eval_parser(_Broken(), _cases(), cache_dir=None)
    assert report.errors == 1
    assert report.schema_valid_rate == 0
    assert "schema-valid below 99.5%" in parser_gates(report)


def test_a_second_run_replays_the_cache(tmp_path) -> None:
    calls = {"n": 0}

    class _Once:
        parser_id = "api:once"

        def parse(self, posting: PostingInput) -> JobDetail:
            calls["n"] += 1
            return JobDetail(
                role=TextFact(
                    value="software", confidence=1, evidence=posting.title, parser_id="api:once"
                )
            )

    first = eval_parser(_Once(), _cases(), cache_dir=tmp_path)
    second = eval_parser(_Once(), _cases(), cache_dir=tmp_path)
    assert first.precision == 1
    assert second.precision == 1
    assert calls["n"] == 1

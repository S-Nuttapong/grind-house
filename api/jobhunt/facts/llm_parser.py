"""Detail parser that pairs any structured LLM with the job-facts spec."""

from jobhunt.core.claude import ClaudeLLM
from jobhunt.core.llm import CallMeta, StructuredLLM
from jobhunt.facts.base import JobDetail, ParseHints, PostingInput, as_input, prefer
from jobhunt.facts.extraction import JOB_FACTS, ExtractionSpec, detail_from_parsed


class LLMParser:
    """Sends the posting to an LLM. Board facts already on the input are kept."""

    def __init__(
        self,
        llm: StructuredLLM | None = None,
        spec: ExtractionSpec = JOB_FACTS,
    ) -> None:
        self.llm = ClaudeLLM() if llm is None else llm
        self.spec = spec
        self.model = self.llm.model_id
        self.parser_id = f"{self.llm.model_id}/{spec.version}"
        self.calls: list[CallMeta] = []
        self.sends_data_offsite = self.llm.sends_data_offsite

    def parse(self, posting: PostingInput | str, hints: ParseHints | None = None) -> JobDetail:
        del hints
        item = as_input(posting)
        parsed, meta = self.llm.complete(
            system=self.spec.system,
            user=self.spec.render_user(item),
            output=self.spec.output,
            max_tokens=self.spec.max_tokens,
        )
        self.calls.append(meta)
        return prefer(item.source_facts, detail_from_parsed(parsed, self.parser_id))

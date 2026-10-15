"""Run parsers in order, filling only fields that are still empty."""

from jobhunt.facts.base import (
    FIELDS,
    DetailParser,
    FieldName,
    JobDetail,
    ParseHints,
    PostingInput,
    as_input,
    prefer,
)


class ChainParser:
    """One DetailParser made of several. Order is per field."""

    parser_id = "chain"
    sends_data_offsite = False

    def __init__(
        self, parsers: list[DetailParser], order: dict[FieldName, list[str]] | None = None
    ) -> None:
        self.parsers = parsers
        self.order = order or {field: [parser.parser_id for parser in parsers] for field in FIELDS}
        self.sends_data_offsite = any(parser.sends_data_offsite for parser in parsers)

    def parse(self, posting: PostingInput | str, hints: ParseHints | None = None) -> JobDetail:
        item = as_input(posting)
        chosen = hints or ParseHints()
        remaining = set(chosen.wanted)
        result = JobDetail()
        tried: dict[FieldName, set[str]] = {field: set() for field in FIELDS}
        by_id = {parser.parser_id: parser for parser in self.parsers}
        while remaining:
            batches: dict[str, set[FieldName]] = {}
            for field in list(remaining):
                parser_id = _next_parser(self.order.get(field, []), tried[field], by_id)
                if parser_id is None:
                    remaining.remove(field)
                    continue
                batches.setdefault(parser_id, set()).add(field)
            if not batches:
                break
            for parser_id, fields in batches.items():
                partial = by_id[parser_id].parse(item, chosen.model_copy(update={"wanted": fields}))
                for field in fields:
                    tried[field].add(parser_id)
                    filled = _take(partial, field)
                    if filled is None:
                        continue
                    result = prefer(result, filled)
                    remaining.discard(field)
        return result


def _next_parser(order: list[str], tried: set[str], by_id: dict[str, DetailParser]) -> str | None:
    for name in order:
        if name in tried or name not in by_id:
            continue
        return name
    return None


def _take(detail: JobDetail, field: FieldName) -> JobDetail | None:
    if field == "pay" and detail.pay is not None:
        return JobDetail(pay=detail.pay)
    if field == "job_type" and detail.job_type is not None:
        return JobDetail(job_type=detail.job_type)
    if field == "workplace" and detail.workplace is not None:
        return JobDetail(workplace=detail.workplace)
    if field == "locations" and detail.locations is not None:
        return JobDetail(locations=detail.locations)
    if field == "posted" and detail.posted is not None:
        return JobDetail(posted=detail.posted)
    if field == "role" and detail.role is not None:
        return JobDetail(role=detail.role)
    if field == "level" and detail.level is not None:
        return JobDetail(level=detail.level)
    if field == "experience" and detail.experience is not None:
        return JobDetail(experience=detail.experience)
    return None

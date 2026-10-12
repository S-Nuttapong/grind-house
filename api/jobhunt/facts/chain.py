"""Run parsers in order, filling only fields that are still empty."""

from jobhunt.facts.base import (
    FIELDS,
    DetailParser,
    FieldName,
    JobDetail,
    ParseHints,
    prefer,
)


def configured_chain() -> "ChainParser":
    """Parsers named in facts.yaml. The api step is not a text parser."""
    from jobhunt.facts.config import chains
    from jobhunt.facts.default import DefaultParser

    order = chains()
    wanted: list[str] = []
    for field_order in order.values():
        for name in field_order:
            if name != "api" and name not in wanted:
                wanted.append(name)
    parsers: list[DetailParser] = []
    for name in wanted:
        if name == "default":
            parsers.append(DefaultParser())
        elif name == "gliner":
            from jobhunt.facts.gliner import GlinerParser

            parsers.append(GlinerParser())
        else:
            raise ValueError(f"unknown facts parser {name!r}")
    return ChainParser(parsers, order)


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

    def parse(self, text: str, hints: ParseHints | None = None) -> JobDetail:
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
                partial = by_id[parser_id].parse(text, chosen.model_copy(update={"wanted": fields}))
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
    return None

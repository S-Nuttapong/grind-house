"""Pay ranges from text. A value is dropped when it is not clearly compensation."""

import re
from decimal import Decimal

from price_parser import Price

from jobhunt.facts.base import Pay, PayFact
from jobhunt.facts.lexicon import cues, reject_words
from jobhunt.scrape.normalize.salary import normalize_salary

_CODES = (
    "USD",
    "EUR",
    "GBP",
    "CAD",
    "AUD",
    "NZD",
    "SGD",
    "HKD",
    "THB",
    "MYR",
    "IDR",
    "INR",
    "JPY",
    "CHF",
    "CZK",
    "PLN",
    "SEK",
    "NOK",
    "DKK",
    "BRL",
    "MXN",
    "PHP",
    "VND",
    "KRW",
    "TWD",
    "AED",
)
_PREFIX = (
    ("ca$", "CAD"),
    ("us$", "USD"),
    ("nz$", "NZD"),
    ("hk$", "HKD"),
    ("a$", "AUD"),
    ("s$", "SGD"),
    ("c$", "CAD"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("฿", "THB"),
    ("rm", "MYR"),
    ("rp", "IDR"),
)
_NUM = r"\d{1,3}(?:[ ,.\u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_AMOUNT = re.compile(
    rf"(?P<pre>CA\$|US\$|NZ\$|HK\$|A\$|S\$|C\$|€|£|฿|RM|Rp|\$|(?:{'|'.join(_CODES)}))"
    rf"\s*(?P<num>{_NUM})\s*(?P<k>[kK])?",
    re.IGNORECASE,
)
_SEP = re.compile(r"^\s*(?:-|–|—|\bto\b)\s*$", re.IGNORECASE)
_YEAR = re.compile(r"per\s*year|per\s*annum|annually|/year|\bpa\b|p\.a\.", re.IGNORECASE)
_MONTH = re.compile(r"per\s*month|/month|monthly", re.IGNORECASE)
_WEEK = re.compile(r"per\s*week|/week|weekly", re.IGNORECASE)
_DAY = re.compile(r"per\s*day|/day|daily", re.IGNORECASE)
_HOUR = re.compile(r"per\s*hour|/hour|/hr|hourly|an hour", re.IGNORECASE)
_USD_YEAR_MIN = Decimal(5000)
_USD_YEAR_MAX = Decimal(2_000_000)


def pay_from_text(
    text: str, country_hint: str | None, parser_id: str, *, require_cue: bool = True
) -> PayFact | None:
    """The first plausible range, preferring the country's own currency."""
    guarded = _jobspy_usd(text, country_hint, require_cue=require_cue)
    found = _ranges(text, require_cue=require_cue)
    if guarded is not None:
        found.insert(0, guarded)
    if not found:
        return None
    chosen = _pick(found, country_hint)
    if chosen is None:
        return None
    pay, evidence = chosen
    if not _plausible(pay):
        return None
    return PayFact(value=pay, confidence=1.0, evidence=evidence, parser_id=parser_id)


def _jobspy_usd(
    text: str, country_hint: str | None, *, require_cue: bool
) -> tuple[Pay, str] | None:
    if country_hint not in (None, "US"):
        return None
    if country_hint is None and not re.search(r"\bUSD\b|US\$", text):
        return None
    from jobspy.util import extract_salary

    interval, low, high, _currency = extract_salary(text)
    if low is None or high is None:
        return None
    match = re.search(r"(?<![A-Za-z])\$\s?\d", text)
    if match is None:
        return None
    window = text[max(0, match.start() - 100) : match.end() + 100]
    if (require_cue and not _cue(window)) or _rejected(window):
        return None
    pay = Pay(
        minimum=Decimal(int(low)),
        maximum=Decimal(int(high)),
        currency="USD",
        interval=_canonical_interval(str(interval) if interval else None),
    )
    return pay, text[match.start() : match.end() + 40].split("\n")[0]


def _ranges(text: str, *, require_cue: bool) -> list[tuple[Pay, str]]:
    matches = list(_AMOUNT.finditer(text))
    found: list[tuple[Pay, str]] = []
    index = 0
    while index < len(matches):
        current = matches[index]
        nxt = matches[index + 1] if index + 1 < len(matches) else None
        if nxt is not None and _SEP.match(text[current.end() : nxt.start()]):
            pay = _pair(current, nxt, text, require_cue=require_cue)
            if pay is not None:
                found.append(pay)
            index += 2
            continue
        single = _single(current, text, require_cue=require_cue)
        if single is not None:
            found.append(single)
        index += 1
    return found


def _pair(
    low: re.Match[str], high: re.Match[str], text: str, *, require_cue: bool
) -> tuple[Pay, str] | None:
    sentence = _sentence(text, low.start())
    if (require_cue and not _cue(sentence)) or _rejected(sentence):
        return None
    left = _number(low)
    right = _number(high)
    if left is None or right is None or right < left:
        return None
    currency = _currency(low) or _currency(high)
    if currency is None:
        return None
    evidence = text[low.start() : high.end()]
    return (
        Pay(
            minimum=left,
            maximum=right,
            currency=currency,
            interval=_interval(sentence, left),
        ),
        evidence,
    )


def _single(match: re.Match[str], text: str, *, require_cue: bool) -> tuple[Pay, str] | None:
    sentence = _sentence(text, match.start())
    if (require_cue and not _cue(sentence)) or _rejected(sentence):
        return None
    if not (_YEAR.search(sentence) or _HOUR.search(sentence) or match.group("k")):
        return None
    number = _number(match)
    currency = _currency(match)
    if number is None or currency is None:
        return None
    return (
        Pay(minimum=number, maximum=None, currency=currency, interval=_interval(sentence, number)),
        text[match.start() : match.end()],
    )


def _number(match: re.Match[str]) -> Decimal | None:
    raw = match.group("num").replace(" ", "").replace("\u00a0", "")
    parsed = Price.fromstring(raw)
    if parsed.amount is None:
        return None
    amount = parsed.amount
    if match.group("k"):
        amount *= 1000
    return amount.quantize(Decimal("1"))


def _currency(match: re.Match[str]) -> str | None:
    prefix = (match.group("pre") or "").casefold()
    if not prefix:
        return None
    for marker, code in _PREFIX:
        if prefix == marker:
            return code
    if prefix == "$":
        return "USD"
    upper = prefix.upper()
    if upper in _CODES:
        return upper
    return None


def _interval(sentence: str, amount: Decimal) -> str | None:
    if _HOUR.search(sentence):
        return "hourly"
    if _DAY.search(sentence):
        return "daily"
    if _WEEK.search(sentence):
        return "weekly"
    if _MONTH.search(sentence):
        return "monthly"
    if _YEAR.search(sentence):
        return "yearly"
    if amount < 350:
        return "hourly"
    if amount < 30000:
        return "monthly"
    return "yearly"


def _canonical_interval(interval: str | None) -> str | None:
    if interval in {"yearly", "monthly", "weekly", "daily", "hourly"}:
        return interval
    return None


def sentence_at(text: str, start: int) -> str:
    """The line or sentence that contains this offset."""
    return _sentence(text, start)


def _sentence(text: str, start: int) -> str:
    left = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start))
    right_nl = text.find("\n", start)
    right_dot = text.find(". ", start)
    ends = [pos for pos in (right_nl, right_dot) if pos != -1]
    right = min(ends) if ends else len(text)
    return text[left + 1 : right]


def _cue(text: str) -> bool:
    folded = text.casefold()
    return any(cue in folded for cue in cues("salary_cues"))


def _rejected(text: str) -> bool:
    folded = text.casefold()
    return any(re.search(rf"\b{re.escape(word)}\b", folded) for word in reject_words())


def _pick(found: list[tuple[Pay, str]], country_hint: str | None) -> tuple[Pay, str] | None:
    if country_hint:
        wanted = _territory_currency(country_hint)
        for pay, evidence in found:
            if pay.currency == wanted:
                return pay, evidence
    return found[0]


def _territory_currency(country: str) -> str | None:
    from babel.core import UnknownLocaleError
    from babel.numbers import get_territory_currencies

    try:
        codes = get_territory_currencies(country.upper())
    except (UnknownLocaleError, LookupError, ValueError):
        return None
    if not codes:
        return None
    return str(codes[0])


def _plausible(pay: Pay) -> bool:
    if pay.currency is None or pay.minimum is None or pay.interval is None:
        return False
    if pay.maximum is not None and pay.maximum < pay.minimum:
        return False
    _low, _high, _code, _interval, usd = normalize_salary(
        pay.minimum, pay.maximum, pay.currency, pay.interval
    )
    if usd is not None:
        return _USD_YEAR_MIN <= usd <= _USD_YEAR_MAX
    if pay.interval == "hourly":
        return Decimal(5) <= pay.minimum <= Decimal(50000)
    if pay.interval == "monthly":
        return Decimal(100) <= pay.minimum <= Decimal(50_000_000)
    return Decimal(1000) <= pay.minimum <= Decimal(500_000_000)

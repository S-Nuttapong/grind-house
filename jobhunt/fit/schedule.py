"""Cron checks and previews for fit schedules. The shared helper PLAN.md §10.1 describes."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cron_descriptor import ExpressionDescriptor
from croniter import croniter

_MIN_GAP_MINUTES = 15


def validate(cron: str, timezone: str) -> list[str]:
    """Return human-readable problems. An empty list means the schedule is usable."""
    problems: list[str] = []
    if not croniter.is_valid(cron):
        problems.append(f"{cron!r} is not a valid cron expression")
        return problems
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        problems.append(f"{timezone!r} is not a known timezone")
        return problems
    gaps = _gaps(cron, zone)
    if gaps and min(gaps) < _MIN_GAP_MINUTES:
        apart = min(gaps)
        problems.append(f"runs would be {apart} minutes apart; the minimum is {_MIN_GAP_MINUTES}")
    return problems


def describe(cron: str) -> str:
    return str(ExpressionDescriptor(cron))


def next_runs(
    cron: str, timezone: str, n: int = 3, *, now: datetime | None = None
) -> list[datetime]:
    zone = ZoneInfo(timezone)
    start = (now or datetime.now(zone)).astimezone(zone)
    iterator = croniter(cron, start)
    return [iterator.get_next(datetime).replace(tzinfo=zone) for _ in range(n)]


def _gaps(cron: str, zone: ZoneInfo) -> list[int]:
    runs = next_runs(cron, zone.key, 4)
    pairs = zip(runs, runs[1:], strict=False)
    return [int((later - earlier).total_seconds() // 60) for earlier, later in pairs]

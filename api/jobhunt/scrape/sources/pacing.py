"""Fixed per-source delay, one empty-page retry, and a circuit breaker.

A token bucket would spread the same few requests across the whole day.
The volume here is about one page per country, so a fixed gap is enough and
has no rate state to get wrong.
"""

from dataclasses import dataclass


@dataclass
class Breaker:
    """Two throttle signals in one tick open the circuit.

    The first opening pauses for 30 minutes. A later opening pauses for 2 hours.
    A tick with no throttle resets the memory of earlier openings.
    """

    prior: int = 0
    signals: int = 0
    opened: bool = False
    pause_minutes: int = 0

    def note_throttle(self) -> None:
        self.signals += 1
        # One 429 after a previous tick already recorded one is the same breach
        # as two 429s in this tick. Keep poking and LinkedIn stays blocked.
        if self.prior + self.signals >= 2:
            self.opened = True
            self.pause_minutes = 120 if self.prior >= 2 else 30

    def note_clean(self) -> None:
        if self.signals == 0:
            self.prior = 0

    def stored(self) -> int:
        if self.opened:
            return 2
        if self.signals == 0:
            return 0
        return self.signals


def empty_is_throttle(body: str, jobs: int) -> bool:
    """A real empty board says so. A short page with no jobs is a silent block."""
    if jobs > 0:
        return False
    lowered = body.lower()
    if "no matching jobs" in lowered or "no jobs matched" in lowered:
        return False
    return len(body) < 15_000

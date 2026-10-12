"""Maps RESUME_AGENT to a factory. claude-sdk is the default; fake is for tests."""

import os
from collections.abc import Callable

from jobhunt.resume.base import ResumeAgent
from jobhunt.resume.fake import FakeResumeAgent

_FACTORIES: dict[str, Callable[[], ResumeAgent]] = {
    "fake": FakeResumeAgent,
    "claude-sdk": lambda: _sdk(),
}


def names() -> list[str]:
    return sorted(_FACTORIES)


def create(name: str | None = None) -> ResumeAgent:
    chosen = name or os.environ.get("RESUME_AGENT", "claude-sdk")
    factory = _FACTORIES.get(chosen)
    if factory is None:
        known = ", ".join(names())
        raise ValueError(f"unknown resume agent {chosen!r}; known: {known}")
    agent = factory()
    if agent.sends_data_offsite and os.environ.get("FIT_ALLOW_OFFSITE") != "1":
        raise ValueError(
            f"{chosen} sends brag docs off this machine; set FIT_ALLOW_OFFSITE=1 to load it"
        )
    return agent


def _sdk() -> ResumeAgent:
    from jobhunt.resume.sdk import ClaudeSdkAgent

    return ClaudeSdkAgent()

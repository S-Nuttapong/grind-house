"""The contract every resume generator implements."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from jobhunt.fit.base import BragDoc


@dataclass(frozen=True)
class ResumeRequest:
    """What one generation attempt is allowed to see."""

    job_id: int
    job_description: str
    shortlist: list[BragDoc]
    filler: list[BragDoc]
    profile: str
    aspects: dict[str, str]
    feedback: list[str]


@dataclass(frozen=True)
class AgentUsage:
    """Token use for one attempt. No prompt or output text."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    num_turns: int
    duration_ms: int
    cost_usd: Decimal
    cost_source: str


@dataclass(frozen=True)
class ResumeDraft:
    """One rendered resume and what it cost to produce."""

    resume_json: dict[str, object]
    pdf: bytes
    lint_report: str
    usage: AgentUsage


class ResumeWriter(ABC):
    """Turns a shortlist and a job description into a one-page resume."""

    agent_id: str
    sends_data_offsite: bool = True

    @abstractmethod
    def generate(self, request: ResumeRequest, workdir: Path) -> ResumeDraft:
        """Write the resume into workdir and return the files plus usage."""

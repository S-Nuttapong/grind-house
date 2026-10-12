"""A deterministic agent for tests. It writes a fixed resume and a one-page PDF."""

import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter

from jobhunt.resume.base import AgentUsage, ResumeDraft, ResumeRequest, ResumeWriter

_LINT = "# Resume lint — 0 FAIL · 0 WARN\n"


class FakeResumeWriter(ResumeWriter):
    """passes_on_attempt is 1-based. Later attempts keep failing when it is above 3."""

    agent_id = "fake/v1"
    sends_data_offsite = False

    def __init__(self, *, passes_on_attempt: int = 1) -> None:
        self.passes_on_attempt = passes_on_attempt
        self.calls = 0

    def generate(self, request: ResumeRequest, workdir: Path) -> ResumeDraft:
        self.calls += 1
        strong = self.calls >= self.passes_on_attempt
        bullets = [
            {"text": doc.text if strong else "unrelated", "src": [doc.id]}
            for doc in request.shortlist
        ]
        if request.filler:
            filler = request.filler[0]
            bullets.append({"text": filler.text, "src": [filler.id]})
        resume: dict[str, object] = {
            "name": "Test Candidate",
            "experience": [
                {
                    "company": "Example",
                    "roles": [
                        {
                            "title": "Engineer",
                            "start": "Jan 2024",
                            "end": "Present",
                            "bullets": bullets,
                        }
                    ],
                }
            ],
        }
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "resume.json").write_text(json.dumps(resume))
        pdf = _one_page_pdf()
        (workdir / "resume.pdf").write_bytes(pdf)
        (workdir / "lint.txt").write_text(_LINT)
        return ResumeDraft(
            resume_json=resume,
            pdf=pdf,
            lint_report=_LINT,
            usage=AgentUsage(
                model="fake",
                input_tokens=10,
                output_tokens=20,
                cache_read_tokens=0,
                cache_write_tokens=0,
                num_turns=1,
                duration_ms=5,
                cost_usd=Decimal("0.010000"),
                cost_source="computed",
            ),
        )


def _one_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()

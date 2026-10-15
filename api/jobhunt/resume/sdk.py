"""Claude Agent SDK adapter. The SDK runs the tool loop; this class bounds it."""

import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from jobhunt.resume.base import AgentUsage, ResumeDraft, ResumeRequest, ResumeWriter
from jobhunt.resume.hooks import deny_reason
from jobhunt.resume.kit import kit_dir
from jobhunt.resume.pricing import estimate

_DEFAULT_MODEL = "claude-opus-5-5"
# One page needs a handful of extra stories. The rest of the bank only adds turns.
_FILLER_LIMIT = 6
# Enough for one schema fix after the first render. A 34-turn run missed the 5-minute check.
_MAX_TURNS = 24
_ATTEMPT_BUDGET_USD = 8


class ClaudeSdkWriter(ResumeWriter):
    agent_id = "claude-sdk/v1"
    sends_data_offsite = True

    def __init__(self, *, model: str | None = None, kit: Path | None = None) -> None:
        self.model = model or os.environ.get("RESUME_MODEL", _DEFAULT_MODEL)
        self.kit = kit or kit_dir()

    def generate(self, request: ResumeRequest, workdir: Path) -> ResumeDraft:
        _stage(workdir, request, self.kit)
        return asyncio.run(self._query(request, workdir))

    async def _query(self, request: ResumeRequest, workdir: Path) -> ResumeDraft:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        captured: dict[str, Any] = {}
        notes: list[str] = []

        def _stderr(line: str) -> None:
            text = line.strip()
            if text and "sk-ant-" not in text:
                notes.append(text)
                del notes[:-12]

        async def pre_tool(
            input_data: dict[str, Any], tool_use_id: str | None, context: object
        ) -> dict[str, Any]:
            _ = tool_use_id, context
            reason = deny_reason(
                str(input_data.get("tool_name") or ""),
                dict(input_data.get("tool_input") or {}),
                workdir,
                self.kit,
            )
            decision = "deny" if reason else "allow"
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason or "allowed",
                }
            }

        options = ClaudeAgentOptions(
            model=self.model,
            cwd=str(workdir),
            cli_path=_cli_path(),
            add_dirs=[str(self.kit)],
            setting_sources=[],
            tools=["Read", "Write", "Bash", "Skill"],
            allowed_tools=["Read", "Write", "Bash", "Skill"],
            skills=["tailor-resume-server"],
            plugins=[{"type": "local", "path": str(self.kit)}],
            max_turns=_MAX_TURNS,
            max_budget_usd=_ATTEMPT_BUDGET_USD,
            effort="low",
            stderr=_stderr,
            permission_mode="acceptEdits",
            hooks={"PreToolUse": [_matcher(pre_tool)]},
        )
        try:
            async for message in query(prompt=_prompt(request, workdir, self.kit), options=options):
                if isinstance(message, ResultMessage):
                    captured = _usage_fields(message)
        except Exception as exc:
            detail = " | ".join(notes)[-500:]
            raise RuntimeError(f"{exc} ({detail})") from exc
        resume_path = workdir / "resume.json"
        pdf_path = workdir / "resume.pdf"
        if not resume_path.is_file() or not pdf_path.is_file():
            detail = " | ".join(notes)[-500:]
            raise RuntimeError(f"the agent did not write resume.json and resume.pdf ({detail})")
        lint_path = workdir / "lint.txt"
        usage = _usage(captured, self.model)
        return ResumeDraft(
            resume_json=json.loads(resume_path.read_text(encoding="utf-8")),
            pdf=pdf_path.read_bytes(),
            lint_report=lint_path.read_text(encoding="utf-8") if lint_path.is_file() else "",
            usage=usage,
        )


def _cli_path() -> str | None:
    """Use RESUME_CLI when the bundled CLI cannot run on this CPU.

    The wheel matches the Python architecture. An x86_64 wheel under Rosetta
    ships an x86_64 CLI that hangs on Apple Silicon without AVX.
    """
    return os.environ.get("RESUME_CLI") or None


def _matcher(hook: Any) -> Any:
    from claude_agent_sdk import HookMatcher

    return HookMatcher(matcher="Write|Bash", hooks=[hook])


def _stage(workdir: Path, request: ResumeRequest, kit: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    from jobhunt.core.prompt_fence import fence

    (workdir / "JD.md").write_text(fence(request.job_description, "JOB POSTING"), encoding="utf-8")
    (workdir / "profile.md").write_text(request.profile, encoding="utf-8")
    (workdir / "shortlist.json").write_text(
        json.dumps(
            [
                {"id": doc.id, "text": doc.text, "aspect": request.aspects.get(doc.id, "")}
                for doc in request.shortlist
            ],
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (workdir / "filler.json").write_text(
        json.dumps(
            [{"id": doc.id, "text": doc.text} for doc in request.filler[:_FILLER_LIMIT]],
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    if request.feedback:
        (workdir / "feedback.md").write_text(
            "\n".join(f"- {line}" for line in request.feedback), encoding="utf-8"
        )
    skill_src = kit / "skills" / "tailor-resume-server" / "SKILL.md"
    if not skill_src.is_file():
        raise FileNotFoundError(
            f"server skill is missing at {skill_src}; run jobhunt resume sync-kit"
        )


def _prompt(request: ResumeRequest, workdir: Path, kit: Path) -> str:
    feedback = ""
    if request.feedback:
        feedback = " Read feedback.md and fix those gaps before anything else."
    return (
        "Use the tailor-resume-server skill. "
        f"The working directory is {workdir}. The kit scripts are in {kit}. "
        f"Job {request.job_id}. Write resume.json, resume.pdf, and lint.txt there. "
        "Read the four input files once, write the resume once, and run render and lint. "
        f"Do not explore.{feedback}"
    )


def _usage_fields(message: Any) -> dict[str, Any]:
    usage = getattr(message, "usage", None) or {}
    if not isinstance(usage, dict):
        usage = {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }
    return {
        "total_cost_usd": getattr(message, "total_cost_usd", None),
        "num_turns": int(getattr(message, "num_turns", 0) or 0),
        "duration_ms": int(getattr(message, "duration_ms", 0) or 0),
        "usage": usage,
    }


def _usage(captured: dict[str, Any], model: str) -> AgentUsage:
    usage = captured.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or usage.get("cache_read_tokens") or 0)
    cache_write = int(
        usage.get("cache_creation_input_tokens") or usage.get("cache_write_tokens") or 0
    )
    reported = captured.get("total_cost_usd")
    if isinstance(reported, int | float) and reported > 0:
        cost = Decimal(str(reported)).quantize(Decimal("0.000001"))
        source = "sdk"
    else:
        cost = estimate(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
        source = "computed"
    return AgentUsage(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        num_turns=int(captured.get("num_turns") or 0),
        duration_ms=int(captured.get("duration_ms") or 0),
        cost_usd=cost,
        cost_source=source,
    )

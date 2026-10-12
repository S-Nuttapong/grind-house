"""Decide whether a tool call stays inside the run.

The agent may read the kit and the working directory. It may write only inside
the working directory. Bash may only run the kit's render and lint scripts.
"""

import shlex
from pathlib import Path

_PYTHON = {"python", "python3"}
_SCRIPTS = {"render_resume.py", "lint_resume.py"}


def deny_reason(
    tool_name: str, tool_input: dict[str, object], workdir: Path, kit: Path
) -> str | None:
    """None allows the call. A string is the reason it is denied."""
    if tool_name == "Write":
        return _deny_write(_path(tool_input), workdir)
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str) or not _bash_allowed(command, kit):
            return "bash may only run render_resume.py or lint_resume.py from the kit"
    return None


def _deny_write(path: Path | None, workdir: Path) -> str | None:
    if path is None:
        return "write needs a file path"
    resolved = path if path.is_absolute() else workdir / path
    try:
        resolved.resolve().relative_to(workdir.resolve())
    except ValueError:
        return "writes must stay in the working directory"
    return None


def _bash_allowed(command: str, kit: Path) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if len(parts) < 2 or Path(parts[0]).name not in _PYTHON:
        return False
    script = Path(parts[1])
    if script.name not in _SCRIPTS:
        return False
    allowed = (kit / script.name).resolve()
    candidate = script.resolve() if script.is_absolute() else (kit / script.name).resolve()
    return candidate == allowed


def _path(tool_input: dict[str, object]) -> Path | None:
    raw = tool_input.get("file_path") or tool_input.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    return Path(raw)

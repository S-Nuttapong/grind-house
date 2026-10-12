"""Run the tick's before and after commands. No shell."""

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from jobhunt.core.db import tx
from jobhunt.core.log import get_logger
from jobhunt.core.paths import API_ROOT, config_path
from jobhunt.scrape import repo

log = get_logger(__name__)


@dataclass
class HookOutcome:
    skip: bool = False


def vpn_state_path() -> Path:
    return Path.home() / ".jobhunt" / "vpn.state"


def run_phase(phase: str, *, config: Path | None = None) -> HookOutcome:
    """Run one phase. ``before_start`` can ask the tick to skip scraping."""
    spec = _load(config)
    tick = spec.get("tick") if isinstance(spec, dict) else None
    hooks = tick.get(phase) if isinstance(tick, dict) else None
    if not isinstance(hooks, list):
        return HookOutcome()
    skip = False
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        failed = _run_one(phase, hook)
        if phase == "before_start" and failed and hook.get("on_fail") == "skip_tick":
            skip = True
            break
    return HookOutcome(skip=skip)


def _run_one(phase: str, hook: dict[str, object]) -> bool:
    name = str(hook.get("name") or "hook")
    command = str(hook.get("run") or "")
    started = time.monotonic()
    code: int | None = None
    error: str | None = None
    try:
        args = shlex.split(command)
        if not args:
            raise ValueError("empty hook command")
        completed = subprocess.run(
            args,
            cwd=API_ROOT.parent,
            timeout=_timeout(hook.get("timeout")),
            check=False,
            capture_output=True,
        )
        code = completed.returncode
    except subprocess.TimeoutExpired:
        error = "timed out"
    except (OSError, ValueError) as exc:
        error = type(exc).__name__
    duration_ms = int((time.monotonic() - started) * 1000)
    log.info("hook %s exit %s in %sms", name, code, duration_ms)
    try:
        with tx() as conn:
            repo.insert_hook(
                conn,
                name=name,
                phase=phase,
                exit_code=code,
                duration_ms=duration_ms,
                error=error,
            )
    except Exception:
        log.exception("could not record hook %s", name)
    return code != 0 or error is not None


def _load(config: Path | None) -> object:
    path = config if config is not None else config_path("scrape.yaml")
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _timeout(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "30s").strip().lower()
    if text.endswith("s"):
        text = text[:-1]
    return float(text)

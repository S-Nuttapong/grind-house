"""Copy the vault kit and the server skill into the directory the worker reads."""

import json
import shutil
from pathlib import Path

_KIT_FILES = (
    "render_resume.py",
    "lint_resume.py",
    "expert-rules.md",
    "jd-analysis.md",
    "qa-checklist.md",
    "resume-json.md",
    "bankutil.py",
)


def kit_dir() -> Path:
    import os

    override = os.environ.get("RESUME_KIT_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "resume-kit"


def template_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def sync_kit(vault_bank: Path, destination: Path | None = None) -> Path:
    """Copy kit scripts from the vault and the server skill from the package template."""
    target = destination or kit_dir()
    source = vault_bank / "_kit"
    missing = [name for name in _KIT_FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"kit is missing {', '.join(missing)} in {source}")
    target.mkdir(parents=True, exist_ok=True)
    for name in _KIT_FILES:
        shutil.copyfile(source / name, target / name)
    template = template_dir() / "SKILL.md"
    for relative in (
        Path(".claude") / "skills" / "tailor-resume-server",
        Path("skills") / "tailor-resume-server",
    ):
        skill = target / relative
        skill.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, skill / "SKILL.md")
    manifest = target / ".claude-plugin"
    manifest.mkdir(parents=True, exist_ok=True)
    (manifest / "plugin.json").write_text(
        json.dumps(
            {
                "name": "tailor-resume-server",
                "description": "Unattended one-page resume from a job shortlist.",
            }
        )
    )
    return target

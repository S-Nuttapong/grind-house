"""Config and migration locations, relative to the api/ project root."""

from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]


def config_path(name: str) -> Path:
    return API_ROOT / "config" / name


def migrations_dir() -> Path:
    return API_ROOT / "db" / "migrations"

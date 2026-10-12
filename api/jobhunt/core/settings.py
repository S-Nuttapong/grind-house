"""Runtime settings. Secrets stay in SecretStr and are never logged."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: SecretStr
    vault_bank_path: Path
    jobhunt_tz: str = "Asia/Bangkok"
    title_similarity: float = 0.85


def load_settings() -> Settings:
    return Settings()

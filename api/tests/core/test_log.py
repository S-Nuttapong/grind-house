import logging

import pytest
from jobhunt.core.log import get_logger, redact


def test_redacts_postgres_password() -> None:
    secret = "postgres://user:pass@host/db"
    assert redact(secret) == "postgres://user:***@host/db"
    assert "pass" not in redact(secret)


def test_log_record_redacts_password() -> None:
    logger = get_logger("jobhunt.test.redact")
    logger.setLevel(logging.INFO)
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Capture()
    logger.addHandler(handler)
    try:
        logger.info("connecting %s", "postgres://user:pass@host/db")
    finally:
        logger.removeHandler(handler)

    assert records
    rendered = records[0].getMessage()
    assert "pass@" not in rendered
    assert "***" in rendered


def test_exception_text_is_redacted() -> None:
    logger = get_logger("jobhunt.test.redact.exc")
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Capture()
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError("failed postgres://user:pass@host/db")
        except RuntimeError:
            logger.exception("database connection failed")
    finally:
        logger.removeHandler(handler)

    assert records
    text = records[0].exc_text or ""
    assert "pass@" not in text
    assert "***" in text


def test_settings_keeps_database_url_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host/db")
    monkeypatch.setenv("VAULT_BANK_PATH", "/tmp/bank")
    from jobhunt.core.settings import load_settings

    settings = load_settings()
    revealed = settings.database_url.get_secret_value()
    assert revealed == "postgres://user:pass@host/db"
    assert "pass" not in str(settings.database_url)

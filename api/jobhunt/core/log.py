"""Logging that strips credentials out of URLs."""

import logging
import re

_CREDENTIAL_URL = re.compile(
    r"([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Replace the password in any URL with ``***``."""
    return _CREDENTIAL_URL.sub(r"\1\2:***@", text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(arg)) for arg in record.args)
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(str(record.exc_info[1]))
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(isinstance(item, RedactFilter) for item in logger.filters):
        logger.addFilter(RedactFilter())
    return logger

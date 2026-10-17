"""Logging with secret redaction applied to every handler."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PATTERNS = [
    re.compile(r"(apikey=)[^&\s'\"]+", re.IGNORECASE),
    # Alpha Vantage rate-limit notices echo the key: "We have detected your API key as XXXX ..."
    re.compile(r"(api key as )[A-Za-z0-9]+", re.IGNORECASE),
    re.compile(r"((?:api[_-]?key|token|secret|password)['\"]?\s*[:=]\s*['\"]?)[^'\"\s,&]+", re.IGNORECASE),
]
_KNOWN_SECRETS: set[str] = set()


def register_secret(value: str) -> None:
    """Redact this exact value from all future log output."""
    if value and len(value) >= 4:
        _KNOWN_SECRETS.add(value)


def redact(text: str) -> str:
    for secret in _KNOWN_SECRETS:
        text = text.replace(secret, "***")
    for pattern in _PATTERNS:
        text = pattern.sub(r"\1***", text)
    return text


def redact_details(value):
    """Redact diagnostics before serialization, without changing non-secret data types."""
    if isinstance(value, dict):
        return {
            redact(str(key)): "***"
            if str(key).lower() in {"apikey", "api_key", "token", "secret", "password"}
            else redact_details(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_details(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(str(value))


def protect_log_handlers() -> None:
    """Also protect handlers supplied by an embedding application or pytest."""
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
    logging.getLogger("urllib3").setLevel(logging.WARNING)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redactor = RedactingFilter()

    file_handler = RotatingFileHandler(
        log_dir / "agent_trading.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    console = logging.StreamHandler()
    for handler in (file_handler, console):
        handler.setFormatter(fmt)
        handler.addFilter(redactor)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console)
    # urllib3 logs full request URLs (which contain the API key) at DEBUG.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

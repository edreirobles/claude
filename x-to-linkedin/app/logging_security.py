"""Redaction helpers for operational logs."""

from __future__ import annotations

import logging
import re


REDACTED = "[REDACTED]"

_AUTHORIZATION_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s,;]+"
)
_COOKIE_HEADER_RE = re.compile(r"(?i)((?:set-)?cookie\s*[:=]\s*)[^\r\n]+")
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:[a-z0-9]+[_-])*(?:access[_-]?token|refresh[_-]?token|"
    r"auth[_-]?token|api[_-]?key|client[_-]?secret|secret[_-]?key|"
    r"bot[_-]?token|li_at|jsessionid|ct0|"
    r"password|database_url)\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}&]+)"
)
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{7,12}:[A-Za-z0-9_-]{20,}\b")
_URI_CREDENTIALS_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^\s/@:]+:)[^\s/@]+(@)")


def redact_sensitive_text(value: object) -> str:
    """Return a printable value with common credentials removed."""
    text = str(value)
    text = _AUTHORIZATION_RE.sub(rf"\1{REDACTED}", text)
    text = _COOKIE_HEADER_RE.sub(rf"\1{REDACTED}", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(rf"\1{REDACTED}", text)
    text = _TELEGRAM_TOKEN_RE.sub(REDACTED, text)
    return _URI_CREDENTIALS_RE.sub(rf"\1{REDACTED}\2", text)


class RedactingFormatter(logging.Formatter):
    """Redact the fully formatted record, including exception tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_text(super().format(record))


def install_log_redaction() -> None:
    """Install redaction on all handlers configured for the root logger."""
    formatter = RedactingFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)

from __future__ import annotations

import re
from typing import Optional, Sequence


_SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|apikey|token|secret|password|pass|pwd)\s*[:=]\s*["\']?([A-Za-z0-9._\-\"]{8,})["\']?'),
    re.compile(r'(?i)(sk-[A-Za-z0-9]{20,})'),
]


_PII_PATTERNS = [
    re.compile(r'\b\d{7,9}[A-Za-z]\b'),
    re.compile(r'\b\d{7,9}\b'),
    re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'),
    re.compile(r'\+?\d[\d\-\s()]{7,}\d'),
]


def redact_string(value: str, secrets: Optional[Sequence[str]] = None) -> str:
    out = value
    for secret in secrets or []:
        if secret:
            out = out.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def redact_secrets(text: str, secrets: Optional[Sequence[str]] = None) -> str:
    out = text
    for secret in secrets or []:
        if secret:
            out = out.replace(secret, "[REDACTED]")
    return out


def _scrub_pii(value: str) -> str:
    out = value
    for pattern in _PII_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


class PIIScrubber:
    @staticmethod
    def scrub(value: str) -> str:
        return _scrub_pii(value)

    @staticmethod
    def safe_text(value: str, secrets: Optional[Sequence[str]] = None) -> str:
        cleaned = redact_string(value, secrets=secrets)
        return PIIScrubber.scrub(cleaned)

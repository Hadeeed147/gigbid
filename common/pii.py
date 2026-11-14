"""PII masking for logs, traces and the audit log (requirement E4 / R9)."""
from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    # card numbers (13-19 digits, optional separators) before phones so they win
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),
    (re.compile(r"\bIBAN[:\s]*[A-Z]{2}\d{2}[A-Z0-9 ]{10,30}\b", re.I), "[IBAN]"),
    (re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d"), "[PHONE]"),
    (re.compile(r"\b(?:paypal|payoneer|venmo|cashapp|zelle)\s*[:@]?\s*\S+", re.I), "[PAYMENT]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1[TOKEN]"),
]

_SENSITIVE_KEYS = {"access_token", "refresh_token", "password", "authorization", "api_key", "token"}


def mask_text(text: str) -> str:
    if not text:
        return text
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    return text


def mask(obj: Any) -> Any:
    """Recursively mask strings; redact values under sensitive keys entirely."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {
            k: ("[REDACTED]" if str(k).lower() in _SENSITIVE_KEYS else mask(v)) for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [mask(v) for v in obj]
    return obj

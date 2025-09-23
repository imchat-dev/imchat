# app/core/security.py
from __future__ import annotations

import re
from typing import Optional


class SecurityError(ValueError):
    """Raised when an input fails a security check."""


_CTRL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_SQLI_PATTERNS = (
    re.compile(r"(?i)';?\s*or\s*'1'='1"),
    re.compile(r"(?i)';?\s*or\s*\d=\d"),
    re.compile(r"(?i)\bunion\b\s+\bselect\b"),
    re.compile(r"(?i)\bdrop\s+table\b"),
    re.compile(r"(?i)\btruncate\s+table\b"),
    re.compile(r"(?i)\balter\s+table\b"),
    re.compile(r"(?i)\bdelete\s+from\b"),
    re.compile(r"(?i)\binsert\s+into\b"),
    re.compile(r"(?i)\bupdate\b\s+\w+\s+set\b"),
    re.compile(r"(?i)\bselect\b\s+\*\s+\bfrom\b"),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"(?i)ignore (?:all|any|the) previous instructions"),
    re.compile(r"(?i)disregard (?:all|any|the) rules"),
    re.compile(r"(?i)from now on you (?:are|must|should)"),
    re.compile(r"(?i)pretend to be"),
    re.compile(r"(?i)you are (?:now|no longer) (?:a|an)"),
    re.compile(r"(?i)system prompt"),
    re.compile(r"(?i)exfiltrate"),
)
_ALLOWED_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


def strip_control_characters(value: str) -> str:
    """Remove ASCII control characters except for tab and newline."""
    return _CTRL_CHARS.sub("", value)


def sanitize_text(text: Optional[str], *, max_length: int = 4000) -> str:
    """Normalize input text before storage or downstream use."""
    if text is None:
        return ""
    # Normalize newlines and drop dangerous control chars
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = strip_control_characters(cleaned)
    cleaned = cleaned.strip()
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned


def detect_sql_injection(text: str) -> Optional[str]:
    for pattern in _SQLI_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def detect_prompt_injection(text: str) -> Optional[str]:
    lowered = text.lower()
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(lowered):
            return pattern.pattern
    return None


def ensure_safe_prompt(text: str, *, max_length: int = 4000) -> str:
    """Sanitize text and raise if suspicious prompt or SQL keywords exist."""
    sanitized = sanitize_text(text, max_length=max_length)
    hit = detect_sql_injection(sanitized) or detect_prompt_injection(sanitized)
    if hit:
        raise SecurityError(f"Potential injection attempt detected: {hit}")
    return sanitized


def sanitize_identifier(value: str, *, label: str = "identifier") -> str:
    sanitized = sanitize_text(value, max_length=128)
    if not sanitized or not _ALLOWED_IDENTIFIER.fullmatch(sanitized):
        raise SecurityError(f"Invalid {label}")
    return sanitized


def sanitize_metadata(value: Optional[str], *, fallback: str = "-", max_length: int = 256) -> str:
    sanitized = sanitize_text(value, max_length=max_length)
    return sanitized or fallback

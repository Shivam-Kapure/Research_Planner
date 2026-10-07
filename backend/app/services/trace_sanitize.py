"""The single redaction boundary for trace data.

Everything persisted to `trace_events` passes through `sanitize()`. It does not rely on callers
behaving: values under credential-like keys are replaced, credential-shaped strings are
redacted wherever they appear, and sizes are bounded.
"""

import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.schemas.trace import MESSAGE_LIMIT, RAW_EXCERPT_LIMIT, TEXT_LIMIT

REDACTED = "[REDACTED]"
MAX_ITEMS = 50
MAX_DEPTH = 6

_SENSITIVE_KEY = re.compile(
    r"(?i)^(?:.*[_\-.])?(?:authorization|proxy-authorization|cookie|set-cookie|api[_\-]?key|"
    r"x-goog-api-key|password|passwd|password[_\-]?hash|secret|client[_\-]?secret|token|"
    r"access[_\-]?token|refresh[_\-]?token|session|session[_\-]?token|token[_\-]?hash|"
    r"credentials?|encryption[_\-]?keys?|ciphertext|private[_\-]?key|database[_\-]?url|dsn)$"
)

_UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_HEX = re.compile(r"^[0-9a-f]+$")
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"gsk_[A-Za-z0-9_\-]{16,}"),  # Groq API keys
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google / Gemini API keys
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}"),  # Authorization header values
    re.compile(r"gAAAAA[A-Za-z0-9_\-=]{20,}"),  # Fernet tokens (encrypted credentials)
    re.compile(r"\$argon2(?:id|i|d)\$[^\s\"']+"),  # password hashes
)
_DB_URL_PASSWORD = re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://[^:/\s@]+:)[^@\s/]+@")
# Opaque high-entropy tokens (session tokens, Fernet keys): ≥32 chars of url-safe base64 with
# both letters and digits. UUIDs and lower-case hex ids (e.g. Semantic Scholar) are kept.
_OPAQUE_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{32,}={0,2}(?![A-Za-z0-9_\-])")


def _redact_opaque(match: re.Match[str]) -> str:
    token = match.group(0)
    if _UUID.match(token) or _HEX.match(token):
        return token
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    return REDACTED if has_digit and has_alpha else token


def redact_text(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _DB_URL_PASSWORD.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)
    return _OPAQUE_TOKEN.sub(_redact_opaque, text)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def sanitize(value: Any, *, limit: int = TEXT_LIMIT, _depth: int = 0) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return _truncate(redact_text(value), limit)
    if _depth >= MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:MAX_ITEMS]:
            name = _truncate(redact_text(str(key)), 64)
            if _SENSITIVE_KEY.match(str(key)):
                out[name] = REDACTED
            else:
                item_limit = {"message": MESSAGE_LIMIT, "raw_excerpt": RAW_EXCERPT_LIMIT}.get(
                    str(key), TEXT_LIMIT
                )
                out[name] = sanitize(item, limit=item_limit, _depth=_depth + 1)
        return out
    if isinstance(value, list | tuple | set | frozenset):
        return [sanitize(v, _depth=_depth + 1) for v in list(value)[:MAX_ITEMS]]
    return _truncate(redact_text(str(value)), limit)

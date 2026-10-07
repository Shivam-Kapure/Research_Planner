"""Shared normalisation helpers for provider responses (bounded, defensive)."""

import re
from datetime import date
from typing import Any

from app.tools.literature.models import MAX_ABSTRACT_CHARS, MAX_AUTHORS, MAX_TITLE_CHARS

_DOI_PREFIX = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/|^doi:\s*", re.IGNORECASE)
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


def as_dict(value: object) -> dict[str, Any]:
    """Provider JSON is untrusted: treat anything that is not an object as empty."""
    return value if isinstance(value, dict) else {}


def normalize_doi(value: object) -> str | None:
    """'https://doi.org/10.1000/ABC.' → '10.1000/abc'. Returns None if it is not a DOI."""
    if not isinstance(value, str):
        return None
    doi = _DOI_PREFIX.sub("", value.strip()).strip().rstrip(".,;").lower()
    return doi if _DOI.match(doi) and len(doi) <= 300 else None


def clean_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clean_title(value: object) -> str | None:
    return clean_text(value, MAX_TITLE_CHARS)


def clean_abstract(value: object) -> str | None:
    return clean_text(value, MAX_ABSTRACT_CHARS)


def clean_authors(names: list[Any]) -> tuple[list[str], int]:
    cleaned = [n for n in (clean_text(x, 200) for x in names) if n]
    return cleaned[:MAX_AUTHORS], len(cleaned)


def clean_year(value: object) -> int | None:
    return value if isinstance(value, int) and 1500 <= value <= 2100 else None


def clean_date(value: object) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def clean_count(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def clean_url(value: object) -> str | None:
    if isinstance(value, str) and value.startswith(("https://", "http://")) and len(value) <= 2000:
        return value
    return None

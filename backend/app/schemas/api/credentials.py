from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, SecretStr, field_validator


class Provider(StrEnum):
    groq = "groq"
    gemini = "gemini"


class CredentialIn(BaseModel):
    api_key: SecretStr = Field(min_length=20, max_length=512)

    @field_validator("api_key", mode="before")
    @classmethod
    def _strip_and_check(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if any(c.isspace() for c in value) or not value.isprintable():
                raise ValueError("API key must not contain whitespace or control characters")
        return value


class CredentialStatus(BaseModel):
    """Metadata only. The API key itself is never returned."""

    provider: Provider
    configured: bool
    key_hint: str | None = None  # last 4 characters, for recognising which key is stored
    status: str | None = None  # unverified | valid | invalid (validation arrives with Phase 4)
    validated_at: datetime | None = None
    updated_at: datetime | None = None

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Repository root: backend/app/config.py -> parents[2]
_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,127}$")


class Settings(BaseSettings):
    """Backend settings, read from environment variables (and the untracked root .env)."""

    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:3000"

    # Async SQLAlchemy URL. A plain postgresql:// URL is converted to the asyncpg driver.
    database_url: SecretStr

    # Comma-separated Fernet keys; the first encrypts, all are tried for decryption (rotation).
    credential_encryption_keys: SecretStr

    session_cookie_name: str = "rp_session"
    session_ttl_days: int = Field(default=7, ge=1, le=30)
    # Must be true in production. Locally, plain-http development needs false.
    session_cookie_secure: bool = True

    # LLM providers. Candidate model IDs are configuration, never code: free-tier availability
    # changes, so each list holds models the provider currently offers on its free tier, in
    # order of preference. Users supply their own keys at runtime (never via env).
    groq_models: Annotated[list[str], NoDecode] = Field(default_factory=list)
    gemini_models: Annotated[list[str], NoDecode] = Field(default_factory=list)
    groq_requests_per_minute: int = Field(default=20, ge=1, le=1000)
    gemini_requests_per_minute: int = Field(default=8, ge=1, le=1000)
    llm_request_timeout_s: float = Field(default=60.0, gt=0, le=300)
    # Optional Gemini thinking budget (thinking tokens count against maxOutputTokens).
    gemini_thinking_budget: int | None = Field(default=None, ge=0, le=32768)

    # Academic sources (free). All optional: both APIs work without credentials at lower
    # limits. OPENALEX_API_KEY and SEMANTIC_SCHOLAR_API_KEY are free keys, never paid plans.
    openalex_email: str | None = None  # OpenAlex "polite pool" contact address
    openalex_api_key: SecretStr | None = None
    semantic_scholar_api_key: SecretStr | None = None
    semantic_scholar_requests_per_minute: int = Field(default=30, ge=1, le=600)
    literature_timeout_s: float = Field(default=20.0, gt=0, le=120)

    @field_validator(
        "openalex_email", "openalex_api_key", "semantic_scholar_api_key", mode="before"
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("groq_models", "gemini_models", mode="before")
    @classmethod
    def _split_models(cls, value: object) -> object:
        if isinstance(value, str):
            value = [m.strip() for m in value.split(",") if m.strip()]
        if isinstance(value, list):
            for model in value:
                if not isinstance(model, str) or not _MODEL_ID.match(model):
                    raise ValueError("model IDs may contain only letters, digits and . _ : / -")
            return list(dict.fromkeys(value))
        return value

    @field_validator("database_url")
    @classmethod
    def _use_asyncpg_driver(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return SecretStr("postgresql+asyncpg://" + url.removeprefix(prefix))
        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return value

    @model_validator(mode="after")
    def _secure_cookies_in_production(self) -> Self:
        if self.environment == "production" and not self.session_cookie_secure:
            raise ValueError("SESSION_COOKIE_SECURE must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

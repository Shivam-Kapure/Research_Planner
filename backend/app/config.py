from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: backend/app/config.py -> parents[2]
_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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

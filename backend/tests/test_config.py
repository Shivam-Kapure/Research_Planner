import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.services.credential_crypto import CredentialEncryptionConfigError

DB = "postgresql+asyncpg://u:p@localhost:5432/x_test"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": DB,
        "credential_encryption_keys": Fernet.generate_key().decode(),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_plain_postgres_url_is_converted_to_asyncpg() -> None:
    settings = _settings(database_url="postgresql://u:p@db.example:5432/app")
    assert (
        settings.database_url.get_secret_value() == "postgresql+asyncpg://u:p@db.example:5432/app"
    )


def test_non_postgres_database_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(database_url="sqlite:///local.db")


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, credential_encryption_keys=Fernet.generate_key().decode())


def test_database_url_is_hidden_in_repr() -> None:
    assert "u:p@" not in repr(_settings())


def test_production_requires_secure_cookies() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="production", session_cookie_secure=False)
    assert _settings(environment="production").session_cookie_secure is True


def test_app_fails_clearly_without_encryption_key() -> None:
    with pytest.raises(
        CredentialEncryptionConfigError, match="CREDENTIAL_ENCRYPTION_KEYS is not set"
    ):
        create_app(_settings(credential_encryption_keys=""))


def test_app_fails_clearly_with_invalid_encryption_key() -> None:
    bad_key = "not-a-valid-fernet-key-but-a-secret"
    with pytest.raises(CredentialEncryptionConfigError, match="is invalid") as exc_info:
        create_app(_settings(credential_encryption_keys=bad_key))
    assert bad_key not in str(exc_info.value)
    assert exc_info.value.__cause__ is None

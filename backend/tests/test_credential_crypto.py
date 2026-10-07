import pytest
from cryptography.fernet import Fernet

from app.services.credential_crypto import CredentialCipher, CredentialDecryptionError

SECRET = "gsk_TESTONLY_plaintext_api_key_value_123456"


def test_round_trip_and_ciphertext_is_not_plaintext() -> None:
    cipher = CredentialCipher(Fernet.generate_key().decode())
    token = cipher.encrypt(SECRET)
    assert SECRET.encode() not in token
    assert cipher.encrypt(SECRET) != token  # random IV per encryption
    assert cipher.decrypt(token) == SECRET


def test_key_rotation_keeps_old_ciphertexts_readable() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token = CredentialCipher(old).encrypt(SECRET)

    rotated_cipher = CredentialCipher(f"{new},{old}")
    assert rotated_cipher.decrypt(token) == SECRET
    rotated = rotated_cipher.rotate(token)
    assert CredentialCipher(new).decrypt(rotated) == SECRET


def test_decryption_failure_does_not_leak_secret_or_keys() -> None:
    key = Fernet.generate_key().decode()
    token = CredentialCipher(Fernet.generate_key().decode()).encrypt(SECRET)
    with pytest.raises(CredentialDecryptionError) as exc_info:
        CredentialCipher(key).decrypt(token)
    message = f"{exc_info.value!s} {exc_info.value!r}"
    assert SECRET not in message and key not in message
    assert exc_info.value.__cause__ is None

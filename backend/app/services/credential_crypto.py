from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class CredentialEncryptionConfigError(RuntimeError):
    pass


class CredentialDecryptionError(RuntimeError):
    pass


class CredentialCipher:
    """Encrypts user provider API keys at rest with MultiFernet.

    The first configured key encrypts; every key is tried on decryption, so keys can be
    rotated by prepending a new key and re-encrypting with `rotate`.
    """

    def __init__(self, keys_csv: str) -> None:
        keys = [k.strip() for k in keys_csv.split(",") if k.strip()]
        if not keys:
            raise CredentialEncryptionConfigError(
                "CREDENTIAL_ENCRYPTION_KEYS is not set; it is required to store provider keys"
            )
        try:
            fernets = [Fernet(k) for k in keys]
        except (ValueError, TypeError):
            # Never include the key material in the error.
            raise CredentialEncryptionConfigError(
                "CREDENTIAL_ENCRYPTION_KEYS is invalid: each entry must be a Fernet key "
                "(32 url-safe base64-encoded bytes)"
            ) from None
        self._fernet = MultiFernet(fernets)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode()
        except InvalidToken:
            raise CredentialDecryptionError(
                "Stored credential cannot be decrypted with the configured keys"
            ) from None

    def rotate(self, token: bytes) -> bytes:
        try:
            return self._fernet.rotate(token)
        except InvalidToken:
            raise CredentialDecryptionError(
                "Stored credential cannot be decrypted with the configured keys"
            ) from None

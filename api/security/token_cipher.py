from cryptography.fernet import Fernet, InvalidToken


class TokenDecryptionError(Exception):
    """Raised when a stored token cannot be decrypted with the configured key."""


class TokenCipher:
    """Encrypts and decrypts the GitHub access token stored at rest."""

    def __init__(self, encryption_key: str) -> None:
        self._fernet = Fernet(encryption_key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as error:
            raise TokenDecryptionError("Stored token could not be decrypted") from error

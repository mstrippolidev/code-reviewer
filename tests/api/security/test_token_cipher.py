"""
    Tests for TokenCipher: Fernet encrypt/decrypt round-trip, no I/O.
"""
import pytest
from cryptography.fernet import Fernet

from api.security.token_cipher import TokenCipher, TokenDecryptionError


def _generate_key() -> str:
    return Fernet.generate_key().decode()


def test_encrypt_then_decrypt_round_trips_to_the_original_plaintext() -> None:
    cipher = TokenCipher(encryption_key=_generate_key())

    ciphertext = cipher.encrypt("gho_realtoken")

    assert cipher.decrypt(ciphertext) == "gho_realtoken"


def test_ciphertext_is_not_the_plaintext() -> None:
    cipher = TokenCipher(encryption_key=_generate_key())

    assert cipher.encrypt("gho_realtoken") != "gho_realtoken"


def test_decrypting_with_a_different_key_raises() -> None:
    ciphertext = TokenCipher(encryption_key=_generate_key()).encrypt("gho_realtoken")

    with pytest.raises(TokenDecryptionError):
        TokenCipher(encryption_key=_generate_key()).decrypt(ciphertext)


def test_decrypting_garbage_raises() -> None:
    cipher = TokenCipher(encryption_key=_generate_key())

    with pytest.raises(TokenDecryptionError):
        cipher.decrypt("not-valid-fernet-ciphertext")

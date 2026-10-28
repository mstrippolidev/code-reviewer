"""
    Tests for secret generation and hashing: pure functions, no I/O.
"""
import re

from api.oauth.token_secrets import generate_secret, hash_secret


def test_generated_secrets_are_unique() -> None:
    assert len({generate_secret() for _ in range(1000)}) == 1000


def test_a_generated_secret_carries_at_least_256_bits() -> None:
    assert len(generate_secret()) >= 43


def test_a_generated_secret_is_url_safe() -> None:
    assert re.fullmatch(r"[A-Za-z0-9_-]+", generate_secret())


def test_hashing_the_same_secret_twice_gives_the_same_hash() -> None:
    assert hash_secret("a-secret") == hash_secret("a-secret")


def test_different_secrets_give_different_hashes() -> None:
    assert hash_secret("a-secret") != hash_secret("another-secret")


def test_a_hash_fits_the_64_character_column() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", hash_secret("a-secret"))


def test_the_hash_does_not_contain_the_secret() -> None:
    secret = generate_secret()

    assert secret not in hash_secret(secret)

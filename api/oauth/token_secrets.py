import hashlib
import secrets

SECRET_BYTES = 32


def generate_secret() -> str:
    return secrets.token_urlsafe(SECRET_BYTES)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()

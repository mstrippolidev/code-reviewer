"""
    BOUND oversized-surface fixture: PasswordHasher's actual job is
    hashing and verifying a password, but every intermediate step of how
    it does that is also exposed publicly, so callers can (and in a large
    codebase, will) start depending on internal steps that were never
    meant to be part of the contract.
"""
import hashlib


class PasswordHasher:
    def hash(self, password: str, salt: str) -> str:
        combined = self.combine_password_and_salt(password, salt)
        digest = self.compute_digest(combined)
        return self.format_digest(digest)

    def verify(self, password: str, salt: str, expected_hash: str) -> bool:
        return self.hash(password, salt) == expected_hash

    def combine_password_and_salt(self, password: str, salt: str) -> str:
        return f"{salt}:{password}"

    def compute_digest(self, combined: str) -> bytes:
        return hashlib.sha256(combined.encode()).digest()

    def format_digest(self, digest: bytes) -> str:
        return digest.hex()

    def generate_salt(self, length: int) -> str:
        return "0" * length

"""Password hashing — PBKDF2-HMAC-SHA256 via stdlib.

Format: `pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>`.

OWASP 2023 recommends ≥600,000 iterations for PBKDF2-SHA256.
Salt is 16 random bytes per password. Constant-time comparison
on verify.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


_DEFAULT_ITERATIONS = 600_000
_SALT_BYTES = 16


def hash_password(
    password: str, *, iterations: int = _DEFAULT_ITERATIONS
) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return (
        f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    if not password or not stored:
        return False
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    if iterations < 100_000 or iterations > 2_000_000:
        return False  # outside sane range
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(actual, expected)

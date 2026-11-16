"""
Password hashing and verification utilities (TR: Сценарий 1).
"""

import hashlib
import hmac
import os


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt_bytes = salt if salt is not None else os.urandom(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 100_000)
    return f"{salt_bytes.hex()}${hashed.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt_hex, expected_hash_hex = stored.split("$", 1)
    try:
        salt_bytes = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 100_000).hex()
    return hmac.compare_digest(computed, expected_hash_hex)

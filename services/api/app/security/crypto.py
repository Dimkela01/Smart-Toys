"""Symmetric encryption for the few secrets stored in the database.

Only the admin TOTP secret needs this today (`admins.totp_secret_enc`). A stolen database
dump should not hand over the second factor as well.

The key comes from TOTP_ENCRYPTION_KEY. For local development, where nobody wants to
generate a key before `make seed`, it is derived from JWT_SECRET instead; the pilot safety
check refuses that, because rotating JWT_SECRET would then lock every admin out.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings


class DecryptionError(Exception):
    """The stored value does not match the current key."""


def derived_key(secret: str) -> str:
    """A stable Fernet key from an arbitrary secret (development only)."""
    raw = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"bruno-totp-secret-encryption",
    ).derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw).decode("ascii")


@lru_cache
def _cipher() -> Fernet:
    key = settings.totp_encryption_key or derived_key(settings.jwt_secret)
    return Fernet(key.encode("ascii"))


def encrypt(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as error:
        raise DecryptionError("stored secret cannot be read with the current key") from error


def reset_cache() -> None:
    """Drop the cached cipher; used by tests that change the key."""
    _cipher.cache_clear()

"""Password and PIN hashing with Argon2id (NFR-06).

Hashing is deliberately slow, so it runs in a worker thread and never blocks the event loop.
"""

from __future__ import annotations

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: argon2-cffi defaults are Argon2id with sensible memory/time cost
_hasher = PasswordHasher()


async def hash_secret(secret: str) -> str:
    return await to_thread.run_sync(_hasher.hash, secret)


async def verify_secret(secret_hash: str, secret: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(secret_hash, secret)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await to_thread.run_sync(_verify)


async def needs_rehash(secret_hash: str) -> bool:
    return await to_thread.run_sync(_hasher.check_needs_rehash, secret_hash)

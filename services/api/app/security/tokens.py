"""Token issuing and verification.

Access tokens are short-lived JWTs (ARCHITECTURE.md §2). Refresh tokens are opaque random
strings: only their SHA-256 hash is stored, so a database dump cannot be replayed.

Token audiences are kept apart by the `typ` claim, which is what stops a child-mode token
from reaching a parent route (ARCHITECTURE.md §9).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import jwt

from app.config import settings

ALGORITHM: Final = "HS256"

TokenType = Literal[
    "parent",
    "admin",
    "child_mode",
    "child_session",
    "verify_email",
    "password_reset",
]

PARENT: Final[TokenType] = "parent"
ADMIN: Final[TokenType] = "admin"
CHILD_MODE: Final[TokenType] = "child_mode"
CHILD_SESSION: Final[TokenType] = "child_session"
VERIFY_EMAIL: Final[TokenType] = "verify_email"
PASSWORD_RESET: Final[TokenType] = "password_reset"


class TokenError(Exception):
    """Raised for an expired, malformed or wrong-audience token."""

    def __init__(self, code: str = "invalid_token") -> None:
        self.code = code
        super().__init__(code)


def encode_token(
    *,
    subject: uuid.UUID | str,
    token_type: TokenType,
    expires_in: timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str, *, expected: TokenType) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise TokenError("token_expired") from error
    except jwt.InvalidTokenError as error:
        raise TokenError("invalid_token") from error
    if payload.get("typ") != expected:
        # e.g. a child-session token presented to a parent endpoint
        raise TokenError("wrong_token_type")
    return payload


def subject_of(payload: dict[str, Any]) -> uuid.UUID:
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as error:
        raise TokenError("invalid_token") from error


# --- parent / admin access tokens -------------------------------------------------------


def access_token(
    *, parent_id: uuid.UUID, token_version: int, device_id: str, token_type: TokenType = PARENT
) -> str:
    return encode_token(
        subject=parent_id,
        token_type=token_type,
        expires_in=timedelta(minutes=settings.access_token_minutes),
        extra={"tv": token_version, "did": device_id},
    )


# --- one-shot email tokens ---------------------------------------------------------------


def verify_email_token(*, parent_id: uuid.UUID) -> str:
    """Valid 24 h (UC-01). Single use: it only works while the address is unverified."""
    return encode_token(
        subject=parent_id,
        token_type=VERIFY_EMAIL,
        expires_in=timedelta(hours=settings.verify_token_hours),
    )


def password_reset_token(*, parent_id: uuid.UUID, token_version: int) -> str:
    """Valid 1 h (UC-02). Single use: resetting bumps `token_version`."""
    return encode_token(
        subject=parent_id,
        token_type=PASSWORD_RESET,
        expires_in=timedelta(hours=settings.reset_token_hours),
        extra={"tv": token_version},
    )


# --- refresh tokens ----------------------------------------------------------------------


def new_refresh_token() -> tuple[str, str]:
    """Return (value for the cookie, hash to store)."""
    value = secrets.token_urlsafe(32)
    return value, hash_refresh_token(value)


def hash_refresh_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def refresh_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_days)

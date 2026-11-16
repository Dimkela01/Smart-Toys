"""Authentication logic: registration, sessions, refresh rotation, password reset.

Rules implemented here come from UC-01 and UC-02:
- no account enumeration: registration and reset always answer the same way;
- 5 failed logins lock the account for 15 minutes;
- a password reset invalidates every issued token and every refresh token;
- a refresh token is single use and bound to one device.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Consent, Parent, RefreshToken
from app.security import tokens
from app.security.passwords import hash_secret, verify_secret
from app.services import audit

logger = logging.getLogger("app.auth")


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def find_parent_by_email(session: AsyncSession, email: str) -> Parent | None:
    result = await session.execute(
        select(Parent).where(Parent.email == normalize_email(email), Parent.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_parent(session: AsyncSession, parent_id: uuid.UUID) -> Parent | None:
    result = await session.execute(select(Parent).where(Parent.id == parent_id, Parent.deleted_at.is_(None)))
    return result.scalar_one_or_none()


# --- registration ------------------------------------------------------------------------


async def register_parent(session: AsyncSession, *, email: str, password: str, locale: str) -> Parent | None:
    """Create a parent with consent records. Returns None if the address is already used."""
    address = normalize_email(email)
    if await find_parent_by_email(session, address) is not None:
        return None

    parent = Parent(
        email=address,
        password_hash=await hash_secret(password),
        locale=locale,
    )
    session.add(parent)
    await session.flush()

    # the privacy summary covers both documents; one row each, with the version (F-02)
    for consent_type in ("terms", "privacy"):
        session.add(
            Consent(
                parent_id=parent.id,
                consent_type=consent_type,
                version=settings.consent_version,
            )
        )
    await audit.record(session, actor_type="parent", actor_id=parent.id, action="parent.registered")
    await session.flush()
    return parent


async def mark_email_verified(session: AsyncSession, parent: Parent) -> None:
    parent.email_verified_at = datetime.now(UTC)
    await audit.record(session, actor_type="parent", actor_id=parent.id, action="parent.email_verified")
    await session.flush()


# --- sessions ----------------------------------------------------------------------------


async def issue_session(session: AsyncSession, *, parent: Parent, device_id: str) -> tuple[str, str]:
    """Return (access token, refresh token value). The refresh value is only ever in a cookie."""
    # one active refresh token per device: replace whatever that device had
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == parent.id,
            RefreshToken.user_type == "parent",
            RefreshToken.device_id == device_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    value, token_hash = tokens.new_refresh_token()
    session.add(
        RefreshToken(
            user_id=parent.id,
            user_type="parent",
            device_id=device_id,
            token_hash=token_hash,
            expires_at=tokens.refresh_expires_at(),
        )
    )
    await session.flush()
    access = tokens.access_token(parent_id=parent.id, token_version=parent.token_version, device_id=device_id)
    return access, value


async def find_refresh_token(session: AsyncSession, value: str) -> RefreshToken | None:
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == tokens.hash_refresh_token(value))
    )
    return result.scalar_one_or_none()


async def revoke_device_tokens(session: AsyncSession, *, parent_id: uuid.UUID, device_id: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == parent_id,
            RefreshToken.device_id == device_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), child_mode_at=None)
    )
    await session.flush()


async def revoke_all_tokens(session: AsyncSession, *, parent_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == parent_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), child_mode_at=None)
    )
    await session.flush()


async def rotate_refresh_token(
    session: AsyncSession, *, row: RefreshToken, parent: Parent
) -> tuple[str, str]:
    """Single use: the presented token is revoked and a fresh one issued for the same device."""
    row.revoked_at = datetime.now(UTC)
    value, token_hash = tokens.new_refresh_token()
    session.add(
        RefreshToken(
            user_id=parent.id,
            user_type=row.user_type,
            device_id=row.device_id,
            token_hash=token_hash,
            child_mode_at=row.child_mode_at,
            expires_at=tokens.refresh_expires_at(),
        )
    )
    await session.flush()
    access = tokens.access_token(
        parent_id=parent.id, token_version=parent.token_version, device_id=row.device_id
    )
    return access, value


# --- passwords ---------------------------------------------------------------------------


async def check_password(parent: Parent, password: str) -> bool:
    return await verify_secret(parent.password_hash, password)


async def set_password(session: AsyncSession, *, parent: Parent, password: str) -> None:
    """Change the password, then invalidate every token issued so far (UC-02 AC)."""
    parent.password_hash = await hash_secret(password)
    parent.token_version += 1
    await revoke_all_tokens(session, parent_id=parent.id)
    await audit.record(session, actor_type="parent", actor_id=parent.id, action="parent.password_reset")
    await session.flush()


# --- PIN (step 4 of M1 uses these from the router) ---------------------------------------


async def set_pin(session: AsyncSession, *, parent: Parent, pin: str) -> None:
    parent.pin_hash = await hash_secret(pin)
    await audit.record(session, actor_type="parent", actor_id=parent.id, action="parent.pin_set")
    await session.flush()


async def check_pin(parent: Parent, pin: str) -> bool:
    if parent.pin_hash is None:
        return False
    return await verify_secret(parent.pin_hash, pin)

"""Admin accounts: creation (by CLI only) and two-factor sign-in.

Admins are team accounts, never self-service: there is no registration endpoint. They are
created with `make seed`, which prints the TOTP provisioning URI once.
"""

from __future__ import annotations

import uuid

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Admin
from app.security import crypto
from app.security.passwords import hash_secret, verify_secret

ISSUER = "Bruno MVP"


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def find_by_email(session: AsyncSession, email: str) -> Admin | None:
    result = await session.execute(select(Admin).where(Admin.email == normalize_email(email)))
    return result.scalar_one_or_none()


async def get_admin(session: AsyncSession, admin_id: uuid.UUID) -> Admin | None:
    result = await session.execute(select(Admin).where(Admin.id == admin_id))
    return result.scalar_one_or_none()


async def create_admin(
    session: AsyncSession, *, email: str, password: str, role: str = "admin"
) -> tuple[Admin, str]:
    """Create a team account. Returns the row and the TOTP secret, shown exactly once."""
    secret = pyotp.random_base32()
    admin = Admin(
        email=normalize_email(email),
        password_hash=await hash_secret(password),
        totp_secret_enc=crypto.encrypt(secret),
        role=role,
    )
    session.add(admin)
    await session.flush()
    return admin, secret


async def rotate_totp(session: AsyncSession, *, admin: Admin) -> str:
    secret = pyotp.random_base32()
    admin.totp_secret_enc = crypto.encrypt(secret)
    await session.flush()
    return secret


def provisioning_uri(*, email: str, secret: str) -> str:
    """Paste into an authenticator app (or render as a QR code)."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def check_totp(*, secret: str, code: str) -> bool:
    # one step of tolerance either way, for clock drift
    return bool(pyotp.TOTP(secret).verify(code, valid_window=1))


async def authenticate(session: AsyncSession, *, email: str, password: str, totp_code: str) -> Admin | None:
    """Both factors must pass. The caller reports one generic failure for either."""
    admin = await find_by_email(session, email)
    if admin is None:
        return None
    if not await verify_secret(admin.password_hash, password):
        return None
    try:
        secret = crypto.decrypt(admin.totp_secret_enc)
    except crypto.DecryptionError:
        # the encryption key changed; the secret must be rotated with the CLI
        return None
    if not check_totp(secret=secret, code=totp_code):
        return None
    return admin

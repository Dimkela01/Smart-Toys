"""Admin sign-in with TOTP (F-20; SPEC.md §3)."""

from __future__ import annotations

import time

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Admin
from app.security import crypto
from app.services import admin as admin_service

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-dovoljno-duga"
LOGIN = "/api/v1/admin/login"


@pytest.fixture
async def admin_secret(session: AsyncSession) -> str:
    """Create a team account and return its TOTP secret."""
    _, secret = await admin_service.create_admin(session, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
    await session.commit()
    return secret


def code_for(secret: str, *, at: float | None = None) -> str:
    totp = pyotp.TOTP(secret)
    return totp.now() if at is None else totp.at(at)


async def _sign_in(client: AsyncClient, secret: str) -> dict[str, str]:
    response = await client.post(
        LOGIN,
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "totp_code": code_for(secret),
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- signing in --------------------------------------------------------------------------


async def test_admin_signs_in_with_both_factors(client: AsyncClient, admin_secret: str) -> None:
    response = await client.post(
        LOGIN,
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "totp_code": code_for(admin_secret),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["admin"]["email"] == ADMIN_EMAIL
    assert body["admin"]["role"] == "admin"
    assert body["expires_in"] == settings.access_token_minutes * 60

    me = await client.get("/api/v1/admin/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL


async def test_either_factor_failing_gives_the_same_answer(client: AsyncClient, admin_secret: str) -> None:
    wrong_password = await client.post(
        LOGIN,
        json={"email": ADMIN_EMAIL, "password": "nope-nope-nope", "totp_code": code_for(admin_secret)},
    )
    wrong_code = await client.post(
        LOGIN, json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": "000000"}
    )
    unknown = await client.post(
        LOGIN,
        json={"email": "nobody@example.com", "password": ADMIN_PASSWORD, "totp_code": "123456"},
    )

    assert wrong_password.status_code == wrong_code.status_code == unknown.status_code == 401
    assert wrong_password.json() == wrong_code.json() == unknown.json()


async def test_a_password_alone_is_not_enough(client: AsyncClient, admin_secret: str) -> None:
    missing = await client.post(LOGIN, json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert missing.status_code == 422

    malformed = await client.post(
        LOGIN, json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": "12345"}
    )
    assert malformed.status_code == 422


async def test_a_code_from_the_previous_step_still_works(client: AsyncClient, admin_secret: str) -> None:
    """One step of tolerance for clock drift."""
    response = await client.post(
        LOGIN,
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "totp_code": code_for(admin_secret, at=time.time() - 30),
        },
    )
    assert response.status_code == 200


async def test_admin_login_locks_after_five_failures(client: AsyncClient, admin_secret: str) -> None:
    wrong = {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": "000000"}
    for _ in range(settings.login_max_attempts):
        assert (await client.post(LOGIN, json=wrong)).status_code == 401

    locked = await client.post(LOGIN, json=wrong)
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "account_locked"

    good = await client.post(
        LOGIN,
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": code_for(admin_secret)},
    )
    assert good.status_code == 423


# --- the TOTP secret at rest -------------------------------------------------------------


async def test_the_totp_secret_is_encrypted_in_the_database(session: AsyncSession, admin_secret: str) -> None:
    row = (await session.execute(select(Admin).where(Admin.email == ADMIN_EMAIL))).scalar_one()
    assert admin_secret not in row.totp_secret_enc
    assert crypto.decrypt(row.totp_secret_enc) == admin_secret


# --- audiences (ARCHITECTURE.md §9) ------------------------------------------------------


async def test_admin_routes_refuse_other_tokens(
    client: AsyncClient, admin_secret: str, parent_headers: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/admin/me")).status_code == 401

    with_parent = await client.get("/api/v1/admin/me", headers=parent_headers)
    assert with_parent.status_code == 403
    assert with_parent.json()["detail"]["code"] == "wrong_token_type"


async def test_an_admin_token_cannot_reach_parent_routes(client: AsyncClient, admin_secret: str) -> None:
    admin_headers = await _sign_in(client, admin_secret)
    for path in ("/api/v1/auth/me", "/api/v1/children"):
        response = await client.get(path, headers=admin_headers)
        assert response.status_code == 403, path
        assert response.json()["detail"]["code"] == "wrong_token_type"


# --- no self-service admin accounts ------------------------------------------------------


async def test_the_seeded_address_can_actually_sign_in(client: AsyncClient, session: AsyncSession) -> None:
    """`make seed` must not create an account the login schema then refuses.

    ADMIN_SEED_EMAIL used to default to admin@localhost, which has no TLD and is rejected
    by the email validator, so the seeded admin could never sign in.
    """
    _, secret = await admin_service.create_admin(
        session, email=settings.admin_seed_email, password=ADMIN_PASSWORD
    )
    await session.commit()

    response = await client.post(
        LOGIN,
        json={
            "email": settings.admin_seed_email,
            "password": ADMIN_PASSWORD,
            "totp_code": code_for(secret),
        },
    )
    assert response.status_code == 200, (
        f"ADMIN_SEED_EMAIL {settings.admin_seed_email!r} is not a usable address: {response.text}"
    )


async def test_there_is_no_admin_registration_endpoint(client: AsyncClient) -> None:
    """Team accounts are created with `make seed`, never over HTTP."""
    response = await client.post(
        "/api/v1/admin/register",
        json={"email": "intruder@example.com", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 404

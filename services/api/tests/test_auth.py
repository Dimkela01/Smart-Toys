"""Auth flows: F-01, F-02, UC-01, UC-02."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Consent, Parent
from app.security import tokens
from tests.conftest import token_from_email

EMAIL = "parent@example.com"
PASSWORD = "dovoljno-duga-sifra"
DEVICE = "device-abcdef12"

REGISTRATION: dict[str, Any] = {
    "email": EMAIL,
    "password": PASSWORD,
    "adult_confirmed": True,
    "consent_accepted": True,
    "locale": "sr",
}


async def register(client: AsyncClient, **overrides: Any) -> Any:
    return await client.post("/api/v1/auth/register", json={**REGISTRATION, **overrides})


async def register_and_verify(client: AsyncClient, sent_emails: list[dict[str, str]]) -> str:
    """Register, follow the verification link, and return the access token."""
    await register(client)
    response = await client.post("/api/v1/auth/verify", json={"token": token_from_email(sent_emails[-1])})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


# --- registration (F-01, F-02, UC-01) ----------------------------------------------------


async def test_register_stores_consent_with_version(
    client: AsyncClient, session: AsyncSession, sent_emails: list[dict[str, str]]
) -> None:
    response = await register(client)
    assert response.status_code == 202
    assert response.json() == {"status": "check_inbox"}

    parent = (await session.execute(select(Parent).where(Parent.email == EMAIL))).scalar_one()
    assert parent.email_verified_at is None
    assert parent.pin_hash is None
    assert parent.password_hash != PASSWORD  # never stored in the clear

    consents = (await session.execute(select(Consent).where(Consent.parent_id == parent.id))).scalars().all()
    assert {row.consent_type for row in consents} == {"terms", "privacy"}
    assert {row.version for row in consents} == {settings.consent_version}
    assert len(sent_emails) == 1


async def test_register_is_case_insensitive_and_does_not_enumerate(
    client: AsyncClient, session: AsyncSession, sent_emails: list[dict[str, str]]
) -> None:
    first = await register(client)
    second = await register(client, email=EMAIL.upper())

    # identical answer, so the caller cannot tell the address was taken (UC-01)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()

    count = await session.scalar(select(func.count()).select_from(Parent))
    assert count == 1
    assert len(sent_emails) == 1  # no second verification mail


@pytest.mark.parametrize(
    "overrides",
    [
        {"adult_confirmed": False},
        {"consent_accepted": False},
        {"password": "short"},
        {"email": "not-an-email"},
    ],
)
async def test_register_rejects_incomplete_consent(
    client: AsyncClient, overrides: dict[str, Any], sent_emails: list[dict[str, str]]
) -> None:
    response = await register(client, **overrides)
    assert response.status_code == 422
    assert sent_emails == []


# --- verification (UC-01) ----------------------------------------------------------------


async def test_verification_link_signs_the_parent_in(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    await register(client)
    response = await client.post("/api/v1/auth/verify", json={"token": token_from_email(sent_emails[-1])})
    body = response.json()
    assert response.status_code == 200
    assert body["parent"]["email_verified"] is True
    # the PIN is still missing, so child features stay closed (UC-01 AC)
    assert body["requires"] == ["pin"]
    assert body["access_token"]


async def test_verification_is_idempotent_and_rejects_rubbish(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    await register(client)
    token = token_from_email(sent_emails[-1])
    assert (await client.post("/api/v1/auth/verify", json={"token": token})).status_code == 200
    assert (await client.post("/api/v1/auth/verify", json={"token": token})).status_code == 200

    bad = await client.post("/api/v1/auth/verify", json={"token": "not.a.real.token"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] in {"invalid_token", "token_expired"}


async def test_resend_verification_never_reveals_accounts(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    unknown = await client.post("/api/v1/auth/verify/resend", json={"email": "nobody@example.com"})
    assert unknown.status_code == 202
    assert sent_emails == []

    await register(client)
    sent_emails.clear()
    known = await client.post("/api/v1/auth/verify/resend", json={"email": EMAIL})
    assert known.status_code == 202
    assert len(sent_emails) == 1


# --- login and lockout (UC-02) -----------------------------------------------------------


async def test_login_reports_what_is_still_missing(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD, "device_id": DEVICE}
    )
    assert response.status_code == 200
    assert response.json()["requires"] == ["email_verification", "pin"]


async def test_login_locks_the_account_after_five_failures(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    await register(client)
    wrong = {"email": EMAIL, "password": "wrong-password", "device_id": DEVICE}

    for _ in range(settings.login_max_attempts):
        assert (await client.post("/api/v1/auth/login", json=wrong)).status_code == 401

    locked = await client.post("/api/v1/auth/login", json=wrong)
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "account_locked"

    # the correct password is refused too, while the lock holds
    with_correct = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD, "device_id": DEVICE}
    )
    assert with_correct.status_code == 423


async def test_unknown_address_is_indistinguishable_from_a_wrong_password(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    await register(client)
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD, "device_id": DEVICE},
    )
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "nope-nope-nope", "device_id": DEVICE}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


async def test_successful_login_clears_the_failure_counter(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    await register(client)
    wrong = {"email": EMAIL, "password": "wrong-password", "device_id": DEVICE}
    for _ in range(settings.login_max_attempts - 1):
        await client.post("/api/v1/auth/login", json=wrong)

    good = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD, "device_id": DEVICE}
    )
    assert good.status_code == 200

    for _ in range(settings.login_max_attempts - 1):
        assert (await client.post("/api/v1/auth/login", json=wrong)).status_code == 401


# --- refresh rotation --------------------------------------------------------------------


async def test_refresh_rotates_and_detects_reuse(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(client, sent_emails)
    first_cookie = client.cookies.get("bruno_refresh")
    assert first_cookie

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    assert client.cookies.get("bruno_refresh") != first_cookie

    # replaying the old cookie must fail and drop the device
    client.cookies.set("bruno_refresh", first_cookie)
    replayed = await client.post("/api/v1/auth/refresh")
    assert replayed.status_code == 401
    assert replayed.json()["detail"]["code"] == "refresh_token_reused"


async def test_refresh_without_a_cookie_is_unauthenticated(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401


async def test_logout_revokes_the_device(client: AsyncClient, sent_emails: list[dict[str, str]]) -> None:
    await register_and_verify(client, sent_emails)
    assert (await client.post("/api/v1/auth/logout")).status_code == 200
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


# --- password reset (UC-02 AC) -----------------------------------------------------------


async def test_password_reset_invalidates_tokens_and_is_single_use(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    access_token = await register_and_verify(client, sent_emails)
    authorized = {"Authorization": f"Bearer {access_token}"}
    assert (await client.get("/api/v1/auth/me", headers=authorized)).status_code == 200

    requested = await client.post("/api/v1/auth/password-reset/request", json={"email": EMAIL})
    assert requested.status_code == 202
    reset_token = token_from_email(sent_emails[-1])

    new_password = "neka-nova-duga-sifra"
    confirmed = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": reset_token, "password": new_password},
    )
    assert confirmed.status_code == 200

    # every token issued before the reset stops working (UC-02 AC)
    assert (await client.get("/api/v1/auth/me", headers=authorized)).status_code == 401
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401

    # the link cannot be used twice
    reused = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": reset_token, "password": "jos-jedna-duga-sifra"},
    )
    assert reused.status_code == 400

    signed_in = await client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": new_password, "device_id": DEVICE},
    )
    assert signed_in.status_code == 200


async def test_password_reset_request_never_reveals_accounts(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    response = await client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert response.status_code == 202
    assert response.json() == {"status": "check_inbox"}
    assert sent_emails == []


# --- token audiences (ARCHITECTURE.md §9) ------------------------------------------------


async def test_a_non_parent_token_cannot_reach_a_parent_route(client: AsyncClient) -> None:
    child_token = tokens.encode_token(
        subject=uuid.uuid4(),
        token_type=tokens.CHILD_SESSION,
        expires_in=timedelta(minutes=5),
    )
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {child_token}"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "wrong_token_type"

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
from tests.conftest import DEFAULT_PASSWORD, DEFAULT_PIN, create_parent, token_from_email

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
    client: AsyncClient, sent_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    await register_and_verify(client, sent_emails)
    first_cookie = client.cookies.get("bruno_refresh")
    assert first_cookie

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    assert client.cookies.get("bruno_refresh") != first_cookie

    # replaying the old cookie much later must fail and drop the device
    monkeypatch.setattr(settings, "refresh_reuse_grace_seconds", 0)
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


# --- regressions found auditing M1 -------------------------------------------------------


async def test_two_tabs_refreshing_at_once_keep_the_session(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    """A benign rotation race is not a leak (it used to sign the parent out).

    Two tabs loading together both send the cookie the browser had, and only one can be
    first to rotate it. Treating the loser as a replay revoked the device, so opening a
    second tab logged the parent out of the account they were sitting in front of.
    """
    await register_and_verify(client, sent_emails)
    shared_cookie = client.cookies.get("bruno_refresh")
    assert shared_cookie

    first = await client.post("/api/v1/auth/refresh")
    assert first.status_code == 200
    rotated_cookie = client.cookies.get("bruno_refresh")
    assert rotated_cookie and rotated_cookie != shared_cookie

    # the second tab's request was already in flight with the old value
    client.cookies.set("bruno_refresh", shared_cookie)
    second = await client.post("/api/v1/auth/refresh")
    assert second.status_code == 200, second.text
    assert second.json()["access_token"]

    # and the winner's cookie still works, so nothing was revoked behind its back
    client.cookies.set("bruno_refresh", rotated_cookie)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200


async def test_verify_binds_the_session_to_the_device_that_opened_the_link(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    """Two devices following the same link must not revoke each other (ARCHITECTURE.md §9).

    The device id used to be derived from the account, so every browser looked like one
    device: the second to open a link revoked the first's refresh token, the first then
    tripped the replay check and dropped itself, and child mode on one phone would have
    locked the other.
    """
    await register(client)
    link_token = token_from_email(sent_emails[-1])

    phone = await client.post(
        "/api/v1/auth/verify", json={"token": link_token, "device_id": "phone-aaaaaaaa"}
    )
    assert phone.status_code == 200, phone.text
    phone_cookie = client.cookies.get("bruno_refresh")
    assert phone_cookie

    laptop = await client.post(
        "/api/v1/auth/verify", json={"token": link_token, "device_id": "laptop-bbbbbbbb"}
    )
    assert laptop.status_code == 200, laptop.text
    laptop_cookie = client.cookies.get("bruno_refresh")
    assert laptop_cookie != phone_cookie

    # the phone's session survives the laptop signing in
    client.cookies.set("bruno_refresh", phone_cookie)
    still_there = await client.post("/api/v1/auth/refresh")
    assert still_there.status_code == 200, still_there.text


async def test_a_forgotten_pin_is_reset_with_the_account_password(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    """UC-21 AC: the PIN is reset from the parent login.

    Requiring the current PIN and nothing else meant a parent who forgot it could never
    set another one.
    """
    headers = await create_parent(client, sent_emails, email="forgot-pin@example.com")

    without_proof = await client.post(
        "/api/v1/auth/pin", json={"pin": "1111", "pin_repeat": "1111"}, headers=headers
    )
    assert without_proof.status_code == 400
    assert without_proof.json()["detail"]["code"] == "current_pin_required"

    wrong_password = await client.post(
        "/api/v1/auth/pin",
        json={"pin": "1111", "pin_repeat": "1111", "password": "not-the-password"},
        headers=headers,
    )
    assert wrong_password.status_code == 401

    reset_it = await client.post(
        "/api/v1/auth/pin",
        json={"pin": "1111", "pin_repeat": "1111", "password": DEFAULT_PASSWORD},
        headers=headers,
    )
    assert reset_it.status_code == 200, reset_it.text

    # the new PIN works and the old one does not
    assert (
        await client.post("/api/v1/auth/pin/verify", json={"pin": "1111"}, headers=headers)
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/pin/verify", json={"pin": DEFAULT_PIN}, headers=headers)
    ).status_code == 401


async def test_the_current_pin_still_changes_the_pin(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    headers = await create_parent(client, sent_emails, email="change-pin@example.com")
    changed = await client.post(
        "/api/v1/auth/pin",
        json={"pin": "2222", "pin_repeat": "2222", "current_pin": DEFAULT_PIN},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text

    wrong = await client.post(
        "/api/v1/auth/pin",
        json={"pin": "3333", "pin_repeat": "3333", "current_pin": "9999"},
        headers=headers,
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "invalid_pin"


async def test_a_forged_forwarded_header_cannot_buy_a_new_rate_limit_bucket(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-06 is per IP, and the caller does not get to say what their IP is.

    Reading the first X-Forwarded-For entry made the limit free to bypass: a different
    value on every request meant a fresh bucket on every request.
    """
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "trust_proxy_headers", False)

    codes = [
        (
            await client.post(
                "/api/v1/auth/verify/resend",
                json={"email": "nobody@example.com"},
                headers={"X-Forwarded-For": f"198.51.100.{index}"},
            )
        ).status_code
        for index in range(1, 7)
    ]
    assert 429 in codes, codes


async def test_behind_a_trusted_proxy_the_last_hop_identifies_the_caller(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a proxy we control, its own appended entry is the one to believe."""
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "trust_proxy_headers", True)

    # the caller forges the left-hand entries; the proxy appended 10.0.0.1 itself
    codes = [
        (
            await client.post(
                "/api/v1/auth/verify/resend",
                json={"email": "nobody@example.com"},
                headers={"X-Forwarded-For": f"203.0.113.{index}, 10.0.0.1"},
            )
        ).status_code
        for index in range(1, 7)
    ]
    assert 429 in codes, codes

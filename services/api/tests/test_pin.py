"""Parent PIN: set, change, verify and lockout (F-01, UC-01 step 5, UC-21 AC)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.config import settings
from tests.conftest import token_from_email

EMAIL = "pin-parent@example.com"
PASSWORD = "dovoljno-duga-sifra"
DEVICE = "device-abcdef12"
PIN = "4821"

REGISTRATION: dict[str, Any] = {
    "email": EMAIL,
    "password": PASSWORD,
    "adult_confirmed": True,
    "consent_accepted": True,
    "locale": "sr",
}


async def _register(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/register", json=REGISTRATION)).status_code == 202


async def _verified_headers(client: AsyncClient, sent_emails: list[dict[str, str]]) -> dict[str, str]:
    await _register(client)
    response = await client.post("/api/v1/auth/verify", json={"token": token_from_email(sent_emails[-1])})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _unverified_headers(client: AsyncClient) -> dict[str, str]:
    await _register(client)
    response = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD, "device_id": DEVICE}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- setting the PIN ---------------------------------------------------------------------


async def test_pin_completes_the_account_setup(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    headers = await _verified_headers(client, sent_emails)

    me_before = await client.get("/api/v1/auth/me", headers=headers)
    assert me_before.json()["requires"] == ["pin"]

    response = await client.post("/api/v1/auth/pin", json={"pin": PIN, "pin_repeat": PIN}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["parent"]["pin_set"] is True
    # nothing left before child features open up (UC-01 AC)
    assert body["requires"] == []


async def test_pin_cannot_be_set_before_the_address_is_verified(client: AsyncClient) -> None:
    headers = await _unverified_headers(client)
    response = await client.post("/api/v1/auth/pin", json={"pin": PIN, "pin_repeat": PIN}, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "email_not_verified"


async def test_pin_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/pin", json={"pin": PIN, "pin_repeat": PIN})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"pin": "123", "pin_repeat": "123"},  # too short
        {"pin": "12345", "pin_repeat": "12345"},  # too long
        {"pin": "abcd", "pin_repeat": "abcd"},  # not digits
        {"pin": "1234", "pin_repeat": "4321"},  # entered twice, must match
    ],
)
async def test_pin_shape_is_enforced(
    client: AsyncClient, sent_emails: list[dict[str, str]], body: dict[str, str]
) -> None:
    headers = await _verified_headers(client, sent_emails)
    response = await client.post("/api/v1/auth/pin", json=body, headers=headers)
    assert response.status_code == 422


# --- verifying the PIN -------------------------------------------------------------------


async def test_verify_pin_accepts_the_right_pin_and_refuses_others(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    headers = await _verified_headers(client, sent_emails)
    await client.post("/api/v1/auth/pin", json={"pin": PIN, "pin_repeat": PIN}, headers=headers)

    good = await client.post("/api/v1/auth/pin/verify", json={"pin": PIN}, headers=headers)
    assert good.status_code == 200
    assert good.json() == {"status": "pin_ok"}

    bad = await client.post("/api/v1/auth/pin/verify", json={"pin": "0000"}, headers=headers)
    assert bad.status_code == 401
    assert bad.json()["detail"]["code"] == "invalid_pin"


async def test_verify_pin_before_one_exists(client: AsyncClient, sent_emails: list[dict[str, str]]) -> None:
    headers = await _verified_headers(client, sent_emails)
    response = await client.post("/api/v1/auth/pin/verify", json={"pin": PIN}, headers=headers)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "pin_not_set"


async def test_five_wrong_pins_lock_for_five_minutes(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    headers = await _verified_headers(client, sent_emails)
    await client.post("/api/v1/auth/pin", json={"pin": PIN, "pin_repeat": PIN}, headers=headers)

    for _ in range(settings.pin_max_attempts):
        wrong = await client.post("/api/v1/auth/pin/verify", json={"pin": "0000"}, headers=headers)
        assert wrong.status_code == 401

    locked = await client.post("/api/v1/auth/pin/verify", json={"pin": "0000"}, headers=headers)
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "pin_locked"

    # the right PIN is refused too, while the lock holds
    with_correct = await client.post("/api/v1/auth/pin/verify", json={"pin": PIN}, headers=headers)
    assert with_correct.status_code == 423


async def test_a_correct_pin_clears_the_failure_counter(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    headers = await _verified_headers(client, sent_emails)
    await client.post("/api/v1/auth/pin", json={"pin": PIN, "pin_repeat": PIN}, headers=headers)

    for _ in range(settings.pin_max_attempts - 1):
        await client.post("/api/v1/auth/pin/verify", json={"pin": "0000"}, headers=headers)
    assert (
        await client.post("/api/v1/auth/pin/verify", json={"pin": PIN}, headers=headers)
    ).status_code == 200

    for _ in range(settings.pin_max_attempts - 1):
        wrong = await client.post("/api/v1/auth/pin/verify", json={"pin": "0000"}, headers=headers)
        assert wrong.status_code == 401


# --- changing the PIN --------------------------------------------------------------------


async def test_changing_the_pin_needs_the_current_one(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    headers = await _verified_headers(client, sent_emails)
    await client.post("/api/v1/auth/pin", json={"pin": PIN, "pin_repeat": PIN}, headers=headers)

    without = await client.post(
        "/api/v1/auth/pin", json={"pin": "1357", "pin_repeat": "1357"}, headers=headers
    )
    assert without.status_code == 400
    assert without.json()["detail"]["code"] == "current_pin_required"

    wrong = await client.post(
        "/api/v1/auth/pin",
        json={"pin": "1357", "pin_repeat": "1357", "current_pin": "0000"},
        headers=headers,
    )
    assert wrong.status_code == 401

    changed = await client.post(
        "/api/v1/auth/pin",
        json={"pin": "1357", "pin_repeat": "1357", "current_pin": PIN},
        headers=headers,
    )
    assert changed.status_code == 200

    assert (
        await client.post("/api/v1/auth/pin/verify", json={"pin": "1357"}, headers=headers)
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/pin/verify", json={"pin": PIN}, headers=headers)
    ).status_code == 401

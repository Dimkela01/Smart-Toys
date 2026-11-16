"""Child mode: the lock, the picker, and getting back out (F-04, UC-05, UC-21).

The point of these tests is that the lock is enforced by the server. A UI-only lock would
pass a "child cannot navigate away" check in the browser and still hand a parent session
back to anyone who reloads the page.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from app.config import settings
from tests.conftest import DEFAULT_PIN, create_parent

CHILD_MODE = "/api/v1/child-mode"


def child_payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "nickname": "Mina",
        "age": 6,
        "language": "sr",
        "interests": ["animals"],
        "avatar_id": "avatar-03",
        "character_id": "bear",
    }
    body.update(overrides)
    return body


async def _family(client: AsyncClient, parent_headers: dict[str, str]) -> dict[str, Any]:
    created = await client.post("/api/v1/children", json=child_payload(), headers=parent_headers)
    assert created.status_code == 201, created.text
    return dict(created.json())


async def _enter(client: AsyncClient, parent_headers: dict[str, str]) -> dict[str, Any]:
    response = await client.post(f"{CHILD_MODE}/enter", headers=parent_headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- entering (UC-05) --------------------------------------------------------------------


async def test_enter_returns_the_pictures_and_nothing_else(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    child = await _family(client, parent_headers)
    entered = await _enter(client, parent_headers)

    assert entered["expires_in"] == settings.child_mode_token_minutes * 60
    assert len(entered["children"]) == 1
    picker = entered["children"][0]
    # a picture and a nickname is all the picker needs (UI.md §3.1)
    assert set(picker) == {"id", "nickname", "avatar_id"}
    assert picker["id"] == child["id"]


async def test_enter_needs_a_child_profile_first(client: AsyncClient, parent_headers: dict[str, str]) -> None:
    response = await client.post(f"{CHILD_MODE}/enter", headers=parent_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_children"


async def test_enter_needs_a_finished_parent_account(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    no_pin = await create_parent(client, sent_emails, email="no-pin-cm@example.com", pin=None)
    response = await client.post(f"{CHILD_MODE}/enter", headers=no_pin)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "pin_not_set"

    assert (await client.post(f"{CHILD_MODE}/enter")).status_code == 401


# --- token audiences (ARCHITECTURE.md §9) ------------------------------------------------


async def test_a_child_token_cannot_reach_parent_routes(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    await _family(client, parent_headers)
    entered = await _enter(client, parent_headers)
    child_mode_headers = _bearer(entered["token"])

    for method, path in [
        ("get", "/api/v1/children"),
        ("get", "/api/v1/auth/me"),
    ]:
        response = await getattr(client, method)(path, headers=child_mode_headers)
        assert response.status_code == 403, path
        assert response.json()["detail"]["code"] == "wrong_token_type"


async def test_a_parent_token_cannot_be_used_as_a_child_token(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    child = await _family(client, parent_headers)
    await _enter(client, parent_headers)

    response = await client.post(
        f"{CHILD_MODE}/select", json={"child_id": child["id"]}, headers=parent_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "wrong_token_type"


# --- picking a child ---------------------------------------------------------------------


async def test_select_returns_what_the_toy_screen_needs(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    child = await _family(client, parent_headers)
    entered = await _enter(client, parent_headers)

    selected = await client.post(
        f"{CHILD_MODE}/select",
        json={"child_id": child["id"]},
        headers=_bearer(entered["token"]),
    )
    assert selected.status_code == 200, selected.text
    body = selected.json()
    assert body["child"]["nickname"] == "Mina"
    assert body["child"]["language"] == "sr"
    assert body["child"]["character_id"] == "bear"
    assert body["child"]["activities_enabled"] == {
        "why": True,
        "story": True,
        "numbers": True,
        "english": True,
    }
    assert body["child"]["first_session_done"] is False
    assert body["expires_in"] == settings.child_session_token_hours * 3600


async def test_select_refuses_a_child_from_another_family(
    client: AsyncClient, sent_emails: list[dict[str, str]], parent_headers: dict[str, str]
) -> None:
    await _family(client, parent_headers)
    entered = await _enter(client, parent_headers)

    stranger_headers = await create_parent(client, sent_emails, email="other-family@example.com")
    stranger_child = await client.post(
        "/api/v1/children", json=child_payload(nickname="Ana"), headers=stranger_headers
    )
    assert stranger_child.status_code == 201

    response = await client.post(
        f"{CHILD_MODE}/select",
        json={"child_id": stranger_child.json()["id"]},
        headers=_bearer(entered["token"]),
    )
    assert response.status_code == 404


# --- the lock itself (UC-05 AC, UC-21) ---------------------------------------------------


async def test_refresh_is_blocked_while_child_mode_is_on(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    await _family(client, parent_headers)

    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    await _enter(client, parent_headers)

    blocked = await client.post("/api/v1/auth/refresh")
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "child_mode_active"


async def test_exit_with_the_pin_unlocks_the_parent_session(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    child = await _family(client, parent_headers)
    entered = await _enter(client, parent_headers)
    selected = await client.post(
        f"{CHILD_MODE}/select",
        json={"child_id": child["id"]},
        headers=_bearer(entered["token"]),
    )
    child_session = _bearer(selected.json()["token"])

    assert (await client.post("/api/v1/auth/refresh")).status_code == 403

    exited = await client.post(f"{CHILD_MODE}/exit", json={"pin": DEFAULT_PIN}, headers=child_session)
    assert exited.status_code == 200
    assert exited.json() == {"status": "unlocked"}

    # the parent can get a session back, and the child token is dead
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    stale = await client.post(f"{CHILD_MODE}/select", json={"child_id": child["id"]}, headers=child_session)
    assert stale.status_code == 403
    assert stale.json()["detail"]["code"] == "child_mode_inactive"


async def test_exit_needs_the_right_pin_and_locks_after_five_tries(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    await _family(client, parent_headers)
    entered = await _enter(client, parent_headers)
    headers = _bearer(entered["token"])

    for _ in range(settings.pin_max_attempts):
        wrong = await client.post(f"{CHILD_MODE}/exit", json={"pin": "0000"}, headers=headers)
        assert wrong.status_code == 401
        assert wrong.json()["detail"]["code"] == "invalid_pin"

    locked = await client.post(f"{CHILD_MODE}/exit", json={"pin": "0000"}, headers=headers)
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "pin_locked"

    # even the right PIN waits out the lock, and the device stays locked
    held = await client.post(f"{CHILD_MODE}/exit", json={"pin": DEFAULT_PIN}, headers=headers)
    assert held.status_code == 423
    assert (await client.post("/api/v1/auth/refresh")).status_code == 403


async def test_logging_out_ends_child_mode_on_that_device(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    """UC-02: logging out also ends child mode on that device."""
    await _family(client, parent_headers)
    entered = await _enter(client, parent_headers)

    assert (await client.post("/api/v1/auth/logout")).status_code == 200

    response = await client.post(
        f"{CHILD_MODE}/select",
        json={"child_id": "00000000-0000-0000-0000-000000000000"},
        headers=_bearer(entered["token"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "child_mode_inactive"

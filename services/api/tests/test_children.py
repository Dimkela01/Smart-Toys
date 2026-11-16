"""Child profiles and the wizard catalog (F-03, UC-03)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app import content
from app.config import settings
from app.models.children import MAX_CHILDREN_PER_PARENT
from tests.conftest import DEFAULT_PASSWORD, create_parent

CHILDREN = "/api/v1/children"


def payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "nickname": "Mina",
        "age": 6,
        "language": "sr",
        "interests": ["animals", "space"],
        "avatar_id": "avatar-03",
        "character_id": "bear",
    }
    body.update(overrides)
    return body


# --- catalog -----------------------------------------------------------------------------


async def test_catalog_offers_twelve_avatars_and_three_characters(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta/catalog")
    assert response.status_code == 200
    body = response.json()

    assert len(body["avatars"]) == 12
    assert len(body["characters"]) == 3
    assert body["interest_suggestions"][:2] == ["animals", "space"]
    assert body["languages"] == ["sr", "en"]
    assert body["limits"]["max_children"] == MAX_CHILDREN_PER_PARENT
    assert body["limits"]["age_min"] == 3 and body["limits"]["age_max"] == 10


def test_every_catalog_asset_exists_on_disk() -> None:
    """A renamed or missing placeholder would show as a broken picture in the picker."""
    public = Path(settings.content_dir).parent / "apps" / "web" / "public"
    if not public.is_dir():  # pragma: no cover - the api container has no web assets
        pytest.skip("web assets are not mounted here")

    missing = [
        item["asset"]
        for item in [*content.avatars(), *content.characters()]
        if not (public / str(item["asset"])).is_file()
    ]
    assert missing == []


async def test_catalog_never_exposes_voice_or_model_ids(client: AsyncClient) -> None:
    """Model names and voices are admin-only (docs/CLAUDE.md §2)."""
    response = await client.get("/api/v1/meta/catalog")
    text = response.text
    for forbidden in ("kokoro", "piper", "qwen", "voices", "internal_only"):
        assert forbidden not in text.lower()


# --- the gate (UC-01 AC) -----------------------------------------------------------------


async def test_children_need_authentication(client: AsyncClient) -> None:
    assert (await client.get(CHILDREN)).status_code == 401


async def test_children_need_a_verified_address(
    client: AsyncClient, sent_emails: list[dict[str, str]]
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "unverified@example.com",
            "password": DEFAULT_PASSWORD,
            "adult_confirmed": True,
            "consent_accepted": True,
            "locale": "sr",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "unverified@example.com",
            "password": DEFAULT_PASSWORD,
            "device_id": "device-abcdef12",
        },
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = await client.get(CHILDREN, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "email_not_verified"


async def test_children_need_a_pin(client: AsyncClient, sent_emails: list[dict[str, str]]) -> None:
    headers = await create_parent(client, sent_emails, email="no-pin@example.com", pin=None)
    response = await client.get(CHILDREN, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "pin_not_set"


# --- creating ----------------------------------------------------------------------------


async def test_create_child_applies_the_uc04_defaults(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    response = await client.post(CHILDREN, json=payload(), headers=parent_headers)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["nickname"] == "Mina"
    assert body["interests"] == ["animals", "space"]
    assert body["first_session_done"] is False

    settings = body["settings"]
    assert settings["activities_enabled"] == {
        "why": True,
        "story": True,
        "numbers": True,
        "english": True,
    }
    assert settings["blocked_topics"] == []
    assert settings["daily_limit_min"] == 20
    assert settings["allowed_from"] == "07:00:00"
    assert settings["allowed_to"] == "20:30:00"
    assert settings["memory_enabled"] is True
    assert settings["transcripts_visible"] is False  # off by default (D3)
    assert settings["alerts_email"] is True


async def test_character_defaults_when_not_chosen(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    response = await client.post(CHILDREN, json=payload(character_id=None), headers=parent_headers)
    assert response.status_code == 201
    assert response.json()["character_id"] == "bear"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"avatar_id": "avatar-99"}, "unknown_avatar"),
        ({"character_id": "dragon"}, "unknown_character"),
    ],
)
async def test_create_child_checks_the_catalog(
    client: AsyncClient, parent_headers: dict[str, str], overrides: dict[str, Any], code: str
) -> None:
    response = await client.post(CHILDREN, json=payload(**overrides), headers=parent_headers)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize(
    "overrides",
    [
        {"nickname": ""},
        {"nickname": "x" * 21},
        {"age": 2},
        {"age": 11},
        {"language": "de"},
        {"interests": ["a", "b", "c", "d", "e", "f"]},
        {"avatar_id": ""},
    ],
)
async def test_create_child_rejects_bad_input(
    client: AsyncClient, parent_headers: dict[str, str], overrides: dict[str, Any]
) -> None:
    response = await client.post(CHILDREN, json=payload(**overrides), headers=parent_headers)
    assert response.status_code == 422


async def test_interests_are_trimmed_and_deduplicated(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    response = await client.post(
        CHILDREN,
        json=payload(interests=["  animals ", "animals", "Animals", "space"]),
        headers=parent_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["interests"] == ["animals", "space"]


async def test_a_blank_interest_is_rejected(client: AsyncClient, parent_headers: dict[str, str]) -> None:
    response = await client.post(CHILDREN, json=payload(interests=["animals", "   "]), headers=parent_headers)
    assert response.status_code == 422


async def test_at_most_five_children_per_family(client: AsyncClient, parent_headers: dict[str, str]) -> None:
    for index in range(MAX_CHILDREN_PER_PARENT):
        created = await client.post(
            CHILDREN,
            json=payload(nickname=f"Dete{index}", avatar_id=f"avatar-{index + 1:02d}"),
            headers=parent_headers,
        )
        assert created.status_code == 201

    too_many = await client.post(
        CHILDREN, json=payload(nickname="Sesti", avatar_id="avatar-09"), headers=parent_headers
    )
    assert too_many.status_code == 409
    assert too_many.json()["detail"]["code"] == "child_limit_reached"


# --- avatar uniqueness (UC-03 AC) --------------------------------------------------------


async def test_avatar_is_unique_within_the_family_but_not_across_families(
    client: AsyncClient, sent_emails: list[dict[str, str]], parent_headers: dict[str, str]
) -> None:
    first = await client.post(CHILDREN, json=payload(), headers=parent_headers)
    assert first.status_code == 201

    clash = await client.post(CHILDREN, json=payload(nickname="Luka"), headers=parent_headers)
    assert clash.status_code == 409
    assert clash.json()["detail"]["code"] == "avatar_taken"

    other_family = await create_parent(client, sent_emails, email="parent-two@example.com")
    reused = await client.post(CHILDREN, json=payload(nickname="Ana"), headers=other_family)
    assert reused.status_code == 201


async def test_deleting_a_child_frees_the_avatar(client: AsyncClient, parent_headers: dict[str, str]) -> None:
    created = await client.post(CHILDREN, json=payload(), headers=parent_headers)
    child_id = created.json()["id"]

    assert (await client.delete(f"{CHILDREN}/{child_id}", headers=parent_headers)).status_code == 204
    assert (await client.get(f"{CHILDREN}/{child_id}", headers=parent_headers)).status_code == 404

    again = await client.post(CHILDREN, json=payload(nickname="Luka"), headers=parent_headers)
    assert again.status_code == 201


# --- reading and updating ----------------------------------------------------------------


async def test_list_and_settings_endpoint(client: AsyncClient, parent_headers: dict[str, str]) -> None:
    created = await client.post(CHILDREN, json=payload(), headers=parent_headers)
    child_id = created.json()["id"]

    listed = await client.get(CHILDREN, headers=parent_headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [child_id]

    settings = await client.get(f"{CHILDREN}/{child_id}/settings", headers=parent_headers)
    assert settings.status_code == 200
    assert settings.json()["daily_limit_min"] == 20


async def test_update_child(client: AsyncClient, parent_headers: dict[str, str]) -> None:
    created = await client.post(CHILDREN, json=payload(), headers=parent_headers)
    child_id = created.json()["id"]

    updated = await client.patch(
        f"{CHILDREN}/{child_id}",
        json={"nickname": "Mina M", "age": 7, "interests": ["music"], "character_id": "robot"},
        headers=parent_headers,
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["nickname"] == "Mina M"
    assert body["age"] == 7
    assert body["interests"] == ["music"]
    assert body["character_id"] == "robot"
    assert body["avatar_id"] == "avatar-03"  # untouched


async def test_update_cannot_take_a_siblings_avatar(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    first = await client.post(CHILDREN, json=payload(), headers=parent_headers)
    second = await client.post(
        CHILDREN, json=payload(nickname="Luka", avatar_id="avatar-05"), headers=parent_headers
    )
    assert second.status_code == 201

    clash = await client.patch(
        f"{CHILDREN}/{second.json()['id']}",
        json={"avatar_id": first.json()["avatar_id"]},
        headers=parent_headers,
    )
    assert clash.status_code == 409
    assert clash.json()["detail"]["code"] == "avatar_taken"

    free = await client.patch(
        f"{CHILDREN}/{second.json()['id']}",
        json={"avatar_id": "avatar-07"},
        headers=parent_headers,
    )
    assert free.status_code == 200


# --- isolation between families ----------------------------------------------------------


async def test_one_family_cannot_see_or_touch_anothers_child(
    client: AsyncClient, sent_emails: list[dict[str, str]], parent_headers: dict[str, str]
) -> None:
    mine = await client.post(CHILDREN, json=payload(), headers=parent_headers)
    child_id = mine.json()["id"]

    stranger = await create_parent(client, sent_emails, email="stranger@example.com")

    assert (await client.get(CHILDREN, headers=stranger)).json() == []
    # 404 rather than 403, so ids cannot be probed
    assert (await client.get(f"{CHILDREN}/{child_id}", headers=stranger)).status_code == 404
    assert (
        await client.patch(f"{CHILDREN}/{child_id}", json={"nickname": "Hacked"}, headers=stranger)
    ).status_code == 404
    assert (await client.delete(f"{CHILDREN}/{child_id}", headers=stranger)).status_code == 404
    assert (await client.get(f"{CHILDREN}/{child_id}/settings", headers=stranger)).status_code == 404

    # still intact for the real parent
    assert (await client.get(f"{CHILDREN}/{child_id}", headers=parent_headers)).status_code == 200

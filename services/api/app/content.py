"""Loader for the shared catalogs in content/.

Characters, avatars and lessons are versioned files in the repository (NFR-11), not rows
in the database, so they can be reviewed in a pull request. Everything still marked
`"status": "draft"` is reported in the milestone report until a human reviews it
(docs/CLAUDE.md §4).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("app.content")

#: interest chips offered in the add-child wizard, verbatim from UC-03; free text is also
#: allowed, so this list is a convenience and not a validation rule
INTEREST_SUGGESTIONS: tuple[str, ...] = (
    "animals",
    "space",
    "dinosaurs",
    "cars",
    "princesses",
    "sport",
    "music",
    "nature",
)


def content_dir() -> Path:
    return Path(settings.content_dir)


@lru_cache
def _load(name: str) -> dict[str, Any]:
    path = content_dir() / name
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error("content file missing: %s", path)
        return {}
    except json.JSONDecodeError as error:
        logger.error("content file %s is not valid JSON: %s", path, error)
        return {}
    return data


def characters() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = _load("characters.json").get("characters", [])
    return items


def avatars() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = _load("avatars.json").get("avatars", [])
    return items


def character_ids() -> set[str]:
    return {str(item["id"]) for item in characters()}


def avatar_ids() -> set[str]:
    return {str(item["id"]) for item in avatars()}


def default_character_id() -> str:
    configured = _load("characters.json").get("default_character")
    if isinstance(configured, str) and configured in character_ids():
        return configured
    ids = sorted(character_ids())
    return ids[0] if ids else "bear"


def character(character_id: str) -> dict[str, Any] | None:
    return next((item for item in characters() if item["id"] == character_id), None)


def voice_is_internal_only(character_id: str, language: str) -> bool:
    """True while a voice licence is unconfirmed (docs/CLAUDE.md §3); used from M2."""
    found = character(character_id)
    if found is None:
        return False
    languages: list[str] = found.get("internal_only_languages", [])
    return language in languages


def draft_files() -> list[str]:
    """Content still marked draft, for the milestone report."""
    drafts: list[str] = []
    for name in ("characters.json", "avatars.json"):
        if _load(name).get("status") == "draft":
            drafts.append(f"content/{name}")
    return drafts


def reload() -> None:
    """Drop the cache; used by tests."""
    _load.cache_clear()

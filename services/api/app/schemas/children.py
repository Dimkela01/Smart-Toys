"""Child profile bodies (F-03, UC-03) and the catalogs the wizard needs.

The parent-facing catalog deliberately leaves out voice and model ids: model names are
admin-only and must never appear in parent or child UI (docs/CLAUDE.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.children import MAX_CHILDREN_PER_PARENT, MAX_INTERESTS

#: 1-20 characters, a nickname rather than a full name (UC-03 AC)
Nickname = Annotated[str, StringConstraints(min_length=1, max_length=20, strip_whitespace=True)]
Age = Annotated[int, Field(ge=3, le=10)]
Interest = Annotated[str, StringConstraints(min_length=1, max_length=30, strip_whitespace=True)]
Language = Literal["sr", "en"]


def _clean_interests(values: list[str]) -> list[str]:
    """Trim, drop blanks and duplicates, keep the order the parent chose."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = value.strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


class ChildCreate(BaseModel):
    nickname: Nickname
    age: Age
    language: Language
    interests: list[Interest] = Field(default_factory=list, max_length=MAX_INTERESTS)
    avatar_id: str = Field(min_length=1, max_length=32)
    #: left out, the default character from content/characters.json is used
    character_id: str | None = Field(default=None, max_length=32)

    @field_validator("interests")
    @classmethod
    def _tidy(cls, values: list[str]) -> list[str]:
        return _clean_interests(values)


class ChildUpdate(BaseModel):
    nickname: Nickname | None = None
    age: Age | None = None
    language: Language | None = None
    interests: list[Interest] | None = Field(default=None, max_length=MAX_INTERESTS)
    avatar_id: str | None = Field(default=None, min_length=1, max_length=32)
    character_id: str | None = Field(default=None, max_length=32)

    @field_validator("interests")
    @classmethod
    def _tidy(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else _clean_interests(values)


class ChildSettingsOut(BaseModel):
    """Read-only in M1; the screen that edits these is M5 (F-10, UC-04)."""

    model_config = ConfigDict(from_attributes=True)

    activities_enabled: dict[str, bool]
    blocked_topics: list[str]
    daily_limit_min: int
    allowed_from: time
    allowed_to: time
    memory_enabled: bool
    transcripts_visible: bool
    alerts_email: bool


class ChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nickname: str
    age: int
    language: str
    interests: list[str]
    avatar_id: str
    character_id: str
    first_session_done: bool
    created_at: datetime
    settings: ChildSettingsOut


class AvatarOut(BaseModel):
    id: str
    asset: str
    color: str | None = None
    label: dict[str, str] = Field(default_factory=dict)


class CharacterOut(BaseModel):
    id: str
    name: dict[str, str]
    asset: str
    #: voice sample; empty until the TTS work in M2 generates the files
    sample: str | None = None


class CatalogLimits(BaseModel):
    max_children: int = MAX_CHILDREN_PER_PARENT
    max_interests: int = MAX_INTERESTS
    nickname_max_length: int = 20
    age_min: int = 3
    age_max: int = 10


class CatalogOut(BaseModel):
    """Everything the add-child wizard needs (UC-03, UI.md §2)."""

    avatars: list[AvatarOut]
    characters: list[CharacterOut]
    interest_suggestions: list[str]
    languages: list[Language]
    limits: CatalogLimits
    consent_version: str

    @staticmethod
    def character_from_content(item: dict[str, Any]) -> CharacterOut:
        return CharacterOut(
            id=str(item["id"]),
            name=dict(item.get("name", {})),
            asset=str(item.get("asset", "")),
            sample=item.get("sample"),
        )

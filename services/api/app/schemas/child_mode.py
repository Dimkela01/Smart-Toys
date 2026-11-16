"""Child mode bodies (F-04, UC-05, UC-21).

The picker needs a picture and a nickname and nothing else; age, interests and settings
stay on the parent side of the API.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import Pin


class ChildPickerOut(BaseModel):
    """One picture in the picker (UI.md §3.1)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nickname: str
    avatar_id: str


class EnterChildModeResponse(BaseModel):
    token: str
    expires_in: int
    children: list[ChildPickerOut]


class SelectChildRequest(BaseModel):
    child_id: uuid.UUID


class ChildToyOut(BaseModel):
    """What the toy screen needs about the child."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nickname: str
    language: str
    character_id: str
    avatar_id: str
    #: disabled activities are hidden rather than greyed out (UI.md §3.2)
    activities_enabled: dict[str, bool] = Field(default_factory=dict)
    #: drives the once-per-child "parents can see" line (SAFETY.md §8), said from M2
    first_session_done: bool = False


class SelectChildResponse(BaseModel):
    token: str
    expires_in: int
    child: ChildToyOut


class ExitChildModeRequest(BaseModel):
    """The hidden corner gesture leads here; there is no "forgot PIN" link (UC-21 AC)."""

    pin: Pin

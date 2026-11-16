"""Admin bodies (SPEC.md §3: email + password + TOTP 2FA)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

TotpCode = Annotated[str, StringConstraints(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")]


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    totp_code: TotpCode


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: str


class AdminSessionResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    admin: AdminOut

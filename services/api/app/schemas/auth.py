"""Request and response bodies for the auth endpoints (ARCHITECTURE.md §7.1)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

#: client-generated, stored per device; a refresh token is bound to it (ARCHITECTURE.md §9)
DeviceId = Annotated[str, StringConstraints(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]

#: minimum 10 characters (UC-01)
Password = Annotated[str, Field(min_length=10, max_length=128)]

#: exactly four digits (UC-01 step 5)
Pin = Annotated[str, StringConstraints(min_length=4, max_length=4, pattern=r"^[0-9]{4}$")]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    #: both boxes are unticked in the UI and must be ticked by the parent (F-02, UC-01)
    adult_confirmed: bool
    consent_accepted: bool
    locale: Literal["sr", "en"] = "sr"

    @field_validator("adult_confirmed")
    @classmethod
    def _must_confirm_adult(cls, value: bool) -> bool:
        if not value:
            raise ValueError("registration requires confirming you are 18 or older")
        return value

    @field_validator("consent_accepted")
    @classmethod
    def _must_accept_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("registration requires accepting the privacy summary")
        return value


class GenericStatus(BaseModel):
    """Deliberately identical whether or not the address exists (UC-01: no enumeration)."""

    status: str


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10)
    #: Which device is being signed in. Without it every browser that follows a link shares
    #: one device identity, and devices then revoke each other's sessions (ARCHITECTURE.md §9).
    device_id: DeviceId | None = None


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    device_id: DeviceId


class ParentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    locale: str
    email_verified: bool
    pin_set: bool


class SessionResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    parent: ParentOut
    #: what the parent still has to do before child features open up (UC-01 AC)
    requires: list[Literal["email_verification", "pin"]] = Field(default_factory=list)


class MeResponse(BaseModel):
    """Account state without issuing a token."""

    parent: ParentOut
    requires: list[Literal["email_verification", "pin"]] = Field(default_factory=list)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10)
    password: Password


class SetPinRequest(BaseModel):
    """The PIN is entered twice (UC-01 step 5)."""

    pin: Pin
    pin_repeat: Pin
    #: Changing an existing PIN needs proof, so a session left open cannot lock the real
    #: parent out of child mode. Either proof will do: the current PIN, or - for a parent
    #: who has forgotten it - the account password, which is UC-21 AC's "reset only from
    #: the parent login".
    current_pin: Pin | None = None
    password: Password | None = None

    @model_validator(mode="after")
    def _must_match(self) -> SetPinRequest:
        if self.pin != self.pin_repeat:
            raise ValueError("the two PINs do not match")
        return self


class VerifyPinRequest(BaseModel):
    pin: Pin

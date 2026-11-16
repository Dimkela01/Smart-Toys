"""Shared FastAPI dependencies.

Token audiences are separated here: a parent route only accepts a `parent` token, so a
child-mode or child-session token is rejected with 403 (ARCHITECTURE.md §9).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import api_error
from app.models import Parent
from app.security import tokens
from app.services import auth as auth_service

_bearer = HTTPBearer(auto_error=False, description="Parent access token")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class ParentPrincipal:
    """The authenticated parent plus the device the token was issued for."""

    parent: Parent
    device_id: str


def requirements_for(parent: Parent) -> list[str]:
    """What is still missing before child features open up (UC-01 AC)."""
    missing: list[str] = []
    if not parent.is_verified:
        missing.append("email_verification")
    if not parent.has_pin:
        missing.append("pin")
    return missing


async def get_parent_principal(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> ParentPrincipal:
    if credentials is None:
        raise api_error(401, "not_authenticated", "Sign in to continue.")
    try:
        payload = tokens.decode_token(credentials.credentials, expected=tokens.PARENT)
    except tokens.TokenError as error:
        # a child-mode token lands here as wrong_token_type
        status = 403 if error.code == "wrong_token_type" else 401
        raise api_error(status, error.code, "Sign in again to continue.") from error

    parent = await auth_service.get_parent(session, tokens.subject_of(payload))
    if parent is None:
        raise api_error(401, "invalid_token", "Sign in again to continue.")
    if payload.get("tv") != parent.token_version:
        # the password was reset after this token was issued (UC-02 AC)
        raise api_error(401, "token_revoked", "Sign in again to continue.")
    return ParentPrincipal(parent=parent, device_id=str(payload.get("did", "")))


async def require_email_verified_parent(
    principal: Annotated[ParentPrincipal, Depends(get_parent_principal)],
) -> ParentPrincipal:
    """For the step between verifying the address and setting the PIN (UC-01 steps 4-5)."""
    if not principal.parent.is_verified:
        raise api_error(403, "email_not_verified", "Confirm your email address first.")
    return principal


async def require_verified_parent(
    principal: Annotated[ParentPrincipal, Depends(get_parent_principal)],
) -> ParentPrincipal:
    """Gate for every child-related route: the address must be verified and a PIN set."""
    missing = requirements_for(principal.parent)
    if "email_verification" in missing:
        raise api_error(403, "email_not_verified", "Confirm your email address first.")
    if "pin" in missing:
        raise api_error(403, "pin_not_set", "Set your parent PIN first.")
    return principal


ParentDep = Annotated[ParentPrincipal, Depends(get_parent_principal)]
EmailVerifiedParentDep = Annotated[ParentPrincipal, Depends(require_email_verified_parent)]
VerifiedParentDep = Annotated[ParentPrincipal, Depends(require_verified_parent)]

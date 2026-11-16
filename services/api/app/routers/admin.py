"""Admin sign-in (F-20; SPEC.md §3, ARCHITECTURE.md §7.1, §9).

Admins are the team: email + password + TOTP. There is no registration endpoint; accounts
are created with `make seed`. Admin pages are never linked from parent pages, and in
deployment they also sit behind a separate host or an IP allow-list (M7).

M1 stops at signing in and an empty layout. The model and prompt registry, evaluation runs,
metrics and rating queues are M6; the registry file itself is models/registry.yaml.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import AdminDep, SessionDep
from app.errors import api_error
from app.schemas.admin import AdminLoginRequest, AdminOut, AdminSessionResponse
from app.security import tokens
from app.security.lockout import ADMIN_LOGIN, register_failure, reset, seconds_remaining
from app.security.ratelimit import RateLimit
from app.services import admin as admin_service
from app.services import audit

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(RateLimit("admin"))])


@router.post("/login", response_model=AdminSessionResponse)
async def login(payload: AdminLoginRequest, session: SessionDep) -> AdminSessionResponse:
    """Both factors are checked, and either failure gives the same answer."""
    locked_for = await seconds_remaining(ADMIN_LOGIN, payload.email)
    if locked_for > 0:
        raise api_error(
            423,
            "account_locked",
            f"Too many attempts. Try again in {max(locked_for // 60, 1)} minutes.",
        )

    admin = await admin_service.authenticate(
        session, email=payload.email, password=payload.password, totp_code=payload.totp_code
    )
    if admin is None:
        await register_failure(ADMIN_LOGIN, payload.email)
        raise api_error(401, "invalid_credentials", "Wrong email address, password or code.")

    await reset(ADMIN_LOGIN, payload.email)
    await audit.record(session, actor_type="admin", actor_id=admin.id, action="admin.signed_in")
    # no refresh token for admins: a short session plus 2FA, and they sign in again
    access = tokens.encode_token(
        subject=admin.id,
        token_type=tokens.ADMIN,
        expires_in=timedelta(minutes=settings.access_token_minutes),
    )
    return AdminSessionResponse(
        access_token=access,
        expires_in=settings.access_token_minutes * 60,
        admin=AdminOut.model_validate(admin),
    )


@router.get("/me", response_model=AdminOut)
async def whoami(admin: AdminDep) -> AdminOut:
    """Used by the empty /admin layout to show who is signed in."""
    return AdminOut.model_validate(admin)

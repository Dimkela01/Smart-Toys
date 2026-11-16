"""Parent authentication endpoints (F-01, F-02, UC-01, UC-02; ARCHITECTURE.md §7.1).

Registration and password reset always answer the same way, whether or not the address
exists, so the API cannot be used to find out who has an account (UC-01 alternatives).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status

from app.config import settings
from app.deps import ParentDep, SessionDep, requirements_for
from app.errors import api_error
from app.models import Parent
from app.schemas.auth import (
    GenericStatus,
    LoginRequest,
    MeResponse,
    ParentOut,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    ResendVerificationRequest,
    SessionResponse,
    VerifyEmailRequest,
)
from app.security import tokens
from app.security.lockout import LOGIN, register_failure, reset, seconds_remaining
from app.security.ratelimit import RateLimit
from app.services import auth as auth_service
from app.services import email as email_service

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(RateLimit("auth"))])

REFRESH_COOKIE = "bruno_refresh"
COOKIE_PATH = "/api/v1/auth"
CHECK_INBOX = GenericStatus(status="check_inbox")


def _set_refresh_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        value,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


def _parent_out(parent: Parent) -> ParentOut:
    return ParentOut(
        id=parent.id,
        email=parent.email,
        locale=parent.locale,
        email_verified=parent.is_verified,
        pin_set=parent.has_pin,
    )


def _session_response(parent: Parent, access_token: str) -> SessionResponse:
    return SessionResponse(
        access_token=access_token,
        expires_in=settings.access_token_minutes * 60,
        parent=_parent_out(parent),
        requires=requirements_for(parent),
    )


@router.post("/register", response_model=GenericStatus, status_code=status.HTTP_202_ACCEPTED)
async def register(payload: RegisterRequest, session: SessionDep) -> GenericStatus:
    """Create a parent account and send the verification link (F-01, F-02, UC-01)."""
    parent = await auth_service.register_parent(
        session, email=payload.email, password=payload.password, locale=payload.locale
    )
    if parent is not None:
        await email_service.send_verification_email(
            to=parent.email, token=tokens.verify_email_token(parent_id=parent.id)
        )
    # identical answer when the address is already in use (no account enumeration)
    return CHECK_INBOX


@router.post("/verify", response_model=SessionResponse)
async def verify_email(
    payload: VerifyEmailRequest, session: SessionDep, response: Response
) -> SessionResponse:
    """Confirm the address. The link is valid 24 h and works only while unverified."""
    try:
        claims = tokens.decode_token(payload.token, expected=tokens.VERIFY_EMAIL)
    except tokens.TokenError as error:
        raise api_error(400, error.code, "This link is no longer valid. Ask for a new one.") from error

    parent = await auth_service.get_parent(session, tokens.subject_of(claims))
    if parent is None:
        raise api_error(400, "invalid_token", "This link is no longer valid. Ask for a new one.")
    if not parent.is_verified:
        await auth_service.mark_email_verified(session, parent)

    # sign the parent in on this device, so the flow continues straight to the PIN screen
    device_id = f"verify-{parent.id.hex[:12]}"
    access, refresh = await auth_service.issue_session(session, parent=parent, device_id=device_id)
    _set_refresh_cookie(response, refresh)
    return _session_response(parent, access)


@router.post("/verify/resend", response_model=GenericStatus, status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(payload: ResendVerificationRequest, session: SessionDep) -> GenericStatus:
    parent = await auth_service.find_parent_by_email(session, payload.email)
    if parent is not None and not parent.is_verified:
        await email_service.send_verification_email(
            to=parent.email, token=tokens.verify_email_token(parent_id=parent.id)
        )
    return CHECK_INBOX


@router.post("/login", response_model=SessionResponse)
async def login(payload: LoginRequest, session: SessionDep, response: Response) -> SessionResponse:
    """Email and password. 5 failed attempts lock the account for 15 minutes (UC-02 AC)."""
    locked_for = await seconds_remaining(LOGIN, payload.email)
    if locked_for > 0:
        raise api_error(
            423,
            "account_locked",
            f"Too many attempts. Try again in {max(locked_for // 60, 1)} minutes.",
        )

    parent = await auth_service.find_parent_by_email(session, payload.email)
    password_ok = parent is not None and await auth_service.check_password(parent, payload.password)
    if parent is None or not password_ok:
        await register_failure(LOGIN, payload.email)
        raise api_error(401, "invalid_credentials", "Wrong email address or password.")

    await reset(LOGIN, payload.email)
    access, refresh = await auth_service.issue_session(session, parent=parent, device_id=payload.device_id)
    _set_refresh_cookie(response, refresh)
    return _session_response(parent, access)


@router.post("/refresh", response_model=SessionResponse)
async def refresh_session(request: Request, session: SessionDep, response: Response) -> SessionResponse:
    """Exchange the refresh cookie for a new access token. Single use, bound to the device."""
    presented = request.cookies.get(REFRESH_COOKIE)
    if not presented:
        raise api_error(401, "not_authenticated", "Sign in to continue.")

    row = await auth_service.find_refresh_token(session, presented)
    if row is None:
        _clear_refresh_cookie(response)
        raise api_error(401, "invalid_refresh_token", "Sign in again to continue.")

    if row.revoked_at is not None:
        # a revoked token being replayed means it leaked: drop the whole device
        await auth_service.revoke_device_tokens(session, parent_id=row.user_id, device_id=row.device_id)
        _clear_refresh_cookie(response)
        raise api_error(401, "refresh_token_reused", "Sign in again to continue.")

    if row.expires_at <= datetime.now(UTC):
        _clear_refresh_cookie(response)
        raise api_error(401, "refresh_token_expired", "Sign in again to continue.")

    if row.child_mode_at is not None:
        # the device is locked in child mode; leaving needs the PIN (UC-05 AC, UC-21)
        raise api_error(403, "child_mode_active", "Child mode is on. The parent PIN unlocks it.")

    parent = await auth_service.get_parent(session, row.user_id)
    if parent is None:
        _clear_refresh_cookie(response)
        raise api_error(401, "invalid_refresh_token", "Sign in again to continue.")

    access, refresh = await auth_service.rotate_refresh_token(session, row=row, parent=parent)
    _set_refresh_cookie(response, refresh)
    return _session_response(parent, access)


@router.post("/logout", response_model=GenericStatus)
async def logout(request: Request, session: SessionDep, response: Response) -> GenericStatus:
    """Revoke this device's refresh token; this also ends child mode on it (UC-02)."""
    presented = request.cookies.get(REFRESH_COOKIE)
    if presented:
        row = await auth_service.find_refresh_token(session, presented)
        if row is not None:
            await auth_service.revoke_device_tokens(session, parent_id=row.user_id, device_id=row.device_id)
    _clear_refresh_cookie(response)
    return GenericStatus(status="signed_out")


@router.post("/password-reset/request", response_model=GenericStatus, status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(payload: PasswordResetRequest, session: SessionDep) -> GenericStatus:
    """Send a reset link valid for 1 h. Same answer for unknown addresses (UC-02)."""
    parent = await auth_service.find_parent_by_email(session, payload.email)
    if parent is not None:
        await email_service.send_password_reset_email(
            to=parent.email,
            token=tokens.password_reset_token(parent_id=parent.id, token_version=parent.token_version),
        )
    return CHECK_INBOX


@router.post("/password-reset/confirm", response_model=GenericStatus)
async def confirm_password_reset(
    payload: PasswordResetConfirm, session: SessionDep, response: Response
) -> GenericStatus:
    """Set a new password; every existing session is invalidated (UC-02 AC)."""
    try:
        claims = tokens.decode_token(payload.token, expected=tokens.PASSWORD_RESET)
    except tokens.TokenError as error:
        raise api_error(400, error.code, "This link is no longer valid. Ask for a new one.") from error

    parent = await auth_service.get_parent(session, tokens.subject_of(claims))
    if parent is None or claims.get("tv") != parent.token_version:
        # the link was already used (token_version moved on) or the account is gone
        raise api_error(400, "invalid_token", "This link is no longer valid. Ask for a new one.")

    await auth_service.set_password(session, parent=parent, password=payload.password)
    await reset(LOGIN, parent.email)
    _clear_refresh_cookie(response)
    return GenericStatus(status="password_changed")


@router.get("/me", response_model=MeResponse)
async def whoami(principal: ParentDep) -> MeResponse:
    """Current account state, so the web app can route to the verify or PIN screen."""
    return MeResponse(
        parent=_parent_out(principal.parent),
        requires=requirements_for(principal.parent),
    )

"""Parent authentication endpoints (F-01, F-02, UC-01, UC-02; ARCHITECTURE.md §7.1).

Registration and password reset always answer the same way, whether or not the address
exists, so the API cannot be used to find out who has an account (UC-01 alternatives).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status

from app.config import settings
from app.deps import EmailVerifiedParentDep, ParentDep, SessionDep, requirements_for
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
    SetPinRequest,
    VerifyEmailRequest,
    VerifyPinRequest,
)
from app.security import tokens
from app.security.lockout import LOGIN, PIN, register_failure, reset, seconds_remaining
from app.security.ratelimit import RateLimit
from app.services import audit
from app.services import auth as auth_service
from app.services import email as email_service

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(RateLimit("auth"))])

#: same prefix, own rate-limit bucket (see Settings.pin_rate_limit_per_minute)
pin_router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(RateLimit("pin", settings.pin_rate_limit_per_minute))],
)

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

    # Sign the parent in on this device, so the flow continues straight to the PIN screen.
    # The device id has to come from the client: deriving it from the account made every
    # browser that opened a verification link look like the same device, so a second one
    # revoked the first's refresh token - and the first then tripped the replay check and
    # dropped itself - while entering child mode on one phone locked the other.
    device_id = payload.device_id or f"verify-{secrets.token_urlsafe(9)}"
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
        age = (datetime.now(UTC) - row.revoked_at).total_seconds()
        successor = await auth_service.active_device_token(
            session, parent_id=row.user_id, device_id=row.device_id
        )
        if age <= settings.refresh_reuse_grace_seconds and successor is not None:
            # Not a leak but a race: two tabs opening at once both send the cookie the
            # browser had, and only one of them can be the first to rotate it. Treating
            # that as a replay signed the parent out of their own account, on the device
            # they were sitting in front of. The loser gets an access token and no new
            # cookie, because the browser already holds the successor's.
            parent = await auth_service.get_parent(session, row.user_id)
            if parent is None:
                _clear_refresh_cookie(response)
                raise api_error(401, "invalid_refresh_token", "Sign in again to continue.")
            if successor.child_mode_at is not None:
                raise api_error(403, "child_mode_active", "Child mode is on. The parent PIN unlocks it.")
            access = tokens.access_token(
                parent_id=parent.id, token_version=parent.token_version, device_id=row.device_id
            )
            return _session_response(parent, access)

        # a revoked token replayed later than that really did leak: drop the whole device
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


async def _guard_pin_lock(parent: Parent) -> None:
    """5 wrong PINs lock the PIN for 5 minutes (UC-21 AC, M1 checklist)."""
    locked_for = await seconds_remaining(PIN, str(parent.id))
    if locked_for > 0:
        raise api_error(
            423, "pin_locked", f"Too many attempts. Try again in {max(locked_for // 60, 1)} minutes."
        )


@pin_router.post("/pin", response_model=MeResponse)
async def set_pin(
    payload: SetPinRequest, principal: EmailVerifiedParentDep, session: SessionDep
) -> MeResponse:
    """Set or change the 4-digit parent PIN, entered twice (UC-01 step 5).

    Changing an existing PIN takes either the current PIN or the account password, so an
    unattended parent session cannot be used to lock the real parent out of child mode.
    The password is the way back for a parent who has forgotten the PIN, which UC-21 AC
    asks for ("reset only from the parent login"); requiring the current PIN alone left a
    forgotten PIN unresettable for good.
    """
    parent = principal.parent
    if parent.has_pin:
        if payload.password is not None:
            # the password is checked against the login lockout, not the PIN one
            locked_for = await seconds_remaining(LOGIN, parent.email)
            if locked_for > 0:
                raise api_error(
                    423,
                    "account_locked",
                    f"Too many attempts. Try again in {max(locked_for // 60, 1)} minutes.",
                )
            if not await auth_service.check_password(parent, payload.password):
                await register_failure(LOGIN, parent.email)
                raise api_error(401, "invalid_credentials", "Wrong email address or password.")
            await reset(LOGIN, parent.email)
        elif payload.current_pin is not None:
            await _guard_pin_lock(parent)
            if not await auth_service.check_pin(parent, payload.current_pin):
                await register_failure(PIN, str(parent.id))
                raise api_error(401, "invalid_pin", "That PIN is not correct.")
        else:
            raise api_error(
                400, "current_pin_required", "Enter your current PIN, or your password, to change it."
            )

    await auth_service.set_pin(session, parent=parent, pin=payload.pin)
    await reset(PIN, str(parent.id))
    return MeResponse(parent=_parent_out(parent), requires=requirements_for(parent))


@pin_router.post("/pin/verify", response_model=GenericStatus)
async def verify_pin(payload: VerifyPinRequest, principal: ParentDep, session: SessionDep) -> GenericStatus:
    """Check the PIN. Used by the parent UI; child mode has its own exit endpoint (UC-21)."""
    parent = principal.parent
    if not parent.has_pin:
        raise api_error(400, "pin_not_set", "Set your parent PIN first.")

    await _guard_pin_lock(parent)
    if not await auth_service.check_pin(parent, payload.pin):
        await register_failure(PIN, str(parent.id))
        raise api_error(401, "invalid_pin", "That PIN is not correct.")

    await reset(PIN, str(parent.id))
    return GenericStatus(status="pin_ok")


@pin_router.post("/unlock", response_model=GenericStatus)
async def unlock_device(
    payload: VerifyPinRequest, request: Request, session: SessionDep, response: Response
) -> GenericStatus:
    """Leave child mode with the PIN when the device's child token is gone (UC-21).

    The toy screen's corner gesture uses /child-mode/exit, which needs the child-mode token
    kept in the browser's sessionStorage. A browser that dropped it - a new tab, a reopened
    Safari, a restored session - would leave the device locked for ever: /auth/refresh
    answers child_mode_active, and nothing else can clear the flag. The refresh cookie names
    the parent and the device, the PIN is the parent's proof, and UC-21 asks for nothing
    more, so this is the same exit by a different door. Same PIN lockout, same bucket.

    Lives under /auth because the refresh cookie's path is /api/v1/auth.
    """
    presented = request.cookies.get(REFRESH_COOKIE)
    if not presented:
        raise api_error(401, "not_authenticated", "Sign in to continue.")

    row = await auth_service.find_refresh_token(session, presented)
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        _clear_refresh_cookie(response)
        raise api_error(401, "invalid_refresh_token", "Sign in again to continue.")

    parent = await auth_service.get_parent(session, row.user_id)
    if parent is None:
        _clear_refresh_cookie(response)
        raise api_error(401, "invalid_refresh_token", "Sign in again to continue.")
    if not parent.has_pin:
        # nothing to unlock with; the device cannot have been locked without a PIN either
        raise api_error(400, "pin_not_set", "Set your parent PIN first.")

    await _guard_pin_lock(parent)
    if not await auth_service.check_pin(parent, payload.pin):
        await register_failure(PIN, str(parent.id))
        raise api_error(401, "invalid_pin", "That PIN is not correct.")

    await reset(PIN, str(parent.id))
    await auth_service.leave_child_mode(session, parent_id=parent.id, device_id=row.device_id)
    await audit.record(session, actor_type="parent", actor_id=parent.id, action="child_mode.exited")
    # the web app now calls /auth/refresh, which hands the parent session back
    return GenericStatus(status="unlocked")


@router.get("/me", response_model=MeResponse)
async def whoami(principal: ParentDep) -> MeResponse:
    """Current account state, so the web app can route to the verify or PIN screen."""
    return MeResponse(
        parent=_parent_out(principal.parent),
        requires=requirements_for(principal.parent),
    )

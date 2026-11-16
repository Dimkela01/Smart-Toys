"""Child mode: hand the phone over, pick a picture, and get back out (F-04, UC-05, UC-21).

Child mode is a lock on a parent's session (D4): children have no credentials. The lock is
enforced on the server, not only in the UI:

- entering sets `child_mode_at` on the device's refresh token, which makes /auth/refresh
  answer 403 child_mode_active, so a parent session cannot be recovered without the PIN;
- child tokens are only accepted while that flag is set, so exiting (or logging out)
  invalidates them immediately;
- child tokens may only reach /child-mode/* and, from M2, /ws/turns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import ChildModeDep, SessionDep, VerifiedParentDep
from app.errors import api_error
from app.schemas.auth import GenericStatus
from app.schemas.child_mode import (
    ChildPickerOut,
    ChildToyOut,
    EnterChildModeResponse,
    ExitChildModeRequest,
    SelectChildRequest,
    SelectChildResponse,
)
from app.security import tokens
from app.security.lockout import PIN, register_failure, reset, seconds_remaining
from app.security.ratelimit import RateLimit
from app.services import audit
from app.services import auth as auth_service
from app.services import children as children_service

router = APIRouter(prefix="/child-mode", tags=["child mode"])


@router.post("/enter", response_model=EnterChildModeResponse)
async def enter_child_mode(principal: VerifiedParentDep, session: SessionDep) -> EnterChildModeResponse:
    """ "Give to child": lock this device and return the family's pictures (UC-05)."""
    parent = principal.parent
    locked = await auth_service.enter_child_mode(session, parent_id=parent.id, device_id=principal.device_id)
    if not locked:
        # no refresh token for this device, so there is no session to lock
        raise api_error(409, "no_device_session", "Sign in again on this device.")

    rows = await children_service.list_children(session, parent_id=parent.id)
    if not rows:
        raise api_error(409, "no_children", "Add a child profile first.")

    await audit.record(session, actor_type="parent", actor_id=parent.id, action="child_mode.entered")
    return EnterChildModeResponse(
        token=tokens.child_mode_token(parent_id=parent.id, device_id=principal.device_id),
        expires_in=settings.child_mode_token_minutes * 60,
        children=[ChildPickerOut.model_validate(row) for row in rows],
    )


@router.post("/select", response_model=SelectChildResponse)
async def select_child(
    payload: SelectChildRequest, principal: ChildModeDep, session: SessionDep
) -> SelectChildResponse:
    """The child taps their picture; no password, no reading required (D4, UC-05)."""
    child = await children_service.get_child(
        session, parent_id=principal.parent.id, child_id=payload.child_id
    )
    await audit.record(
        session,
        actor_type="parent",
        actor_id=principal.parent.id,
        action="child_mode.child_selected",
        target=f"child:{child.id}",
    )
    return SelectChildResponse(
        token=tokens.child_session_token(
            parent_id=principal.parent.id, device_id=principal.device_id, child_id=child.id
        ),
        expires_in=settings.child_session_token_hours * 3600,
        child=ChildToyOut(
            id=child.id,
            nickname=child.nickname,
            language=child.language,
            character_id=child.character_id,
            avatar_id=child.avatar_id,
            activities_enabled=dict(child.settings.activities_enabled),
            first_session_done=child.first_session_done,
        ),
    )


@router.post("/exit", response_model=GenericStatus, dependencies=[Depends(RateLimit("pin"))])
async def exit_child_mode(
    payload: ExitChildModeRequest, principal: ChildModeDep, session: SessionDep
) -> GenericStatus:
    """Leave child mode with the parent PIN; 5 wrong attempts lock it for 5 minutes (UC-21)."""
    parent = principal.parent
    locked_for = await seconds_remaining(PIN, str(parent.id))
    if locked_for > 0:
        raise api_error(
            423,
            "pin_locked",
            f"Too many attempts. Try again in {max(locked_for // 60, 1)} minutes.",
        )

    if not await auth_service.check_pin(parent, payload.pin):
        await register_failure(PIN, str(parent.id))
        raise api_error(401, "invalid_pin", "That PIN is not correct.")

    await reset(PIN, str(parent.id))
    await auth_service.leave_child_mode(session, parent_id=parent.id, device_id=principal.device_id)
    await audit.record(session, actor_type="parent", actor_id=parent.id, action="child_mode.exited")
    # the web app now calls /auth/refresh to get a parent session back
    return GenericStatus(status="unlocked")

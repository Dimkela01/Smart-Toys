"""Child profile endpoints (F-03, UC-03; ARCHITECTURE.md §7.1).

Every route requires a verified address and a parent PIN (UC-01 AC), and only ever sees
the signed-in parent's own children.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.deps import SessionDep, VerifiedParentDep
from app.schemas.children import ChildCreate, ChildOut, ChildSettingsOut, ChildUpdate
from app.services import children as children_service

router = APIRouter(prefix="/children", tags=["children"])


@router.get("", response_model=list[ChildOut])
async def list_children(principal: VerifiedParentDep, session: SessionDep) -> list[ChildOut]:
    rows = await children_service.list_children(session, parent_id=principal.parent.id)
    return [ChildOut.model_validate(row) for row in rows]


@router.post("", response_model=ChildOut, status_code=status.HTTP_201_CREATED)
async def create_child(payload: ChildCreate, principal: VerifiedParentDep, session: SessionDep) -> ChildOut:
    """Add a child profile; settings are created with the UC-04 defaults."""
    child = await children_service.create_child(session, parent=principal.parent, data=payload)
    return ChildOut.model_validate(child)


@router.get("/{child_id}", response_model=ChildOut)
async def get_child(child_id: uuid.UUID, principal: VerifiedParentDep, session: SessionDep) -> ChildOut:
    child = await children_service.get_child(session, parent_id=principal.parent.id, child_id=child_id)
    return ChildOut.model_validate(child)


@router.patch("/{child_id}", response_model=ChildOut)
async def update_child(
    child_id: uuid.UUID, payload: ChildUpdate, principal: VerifiedParentDep, session: SessionDep
) -> ChildOut:
    child = await children_service.get_child(session, parent_id=principal.parent.id, child_id=child_id)
    updated = await children_service.update_child(session, parent=principal.parent, child=child, data=payload)
    return ChildOut.model_validate(updated)


@router.delete("/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_child(child_id: uuid.UUID, principal: VerifiedParentDep, session: SessionDep) -> Response:
    child = await children_service.get_child(session, parent_id=principal.parent.id, child_id=child_id)
    await children_service.delete_child(session, parent=principal.parent, child=child)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{child_id}/settings", response_model=ChildSettingsOut)
async def get_child_settings(
    child_id: uuid.UUID, principal: VerifiedParentDep, session: SessionDep
) -> ChildSettingsOut:
    """Read-only in M1: the wizard shows the defaults before confirming (UC-03 step 4).

    The screen that changes them, and the matching PUT, arrive in M5 (F-10, UC-04).
    """
    child = await children_service.get_child(session, parent_id=principal.parent.id, child_id=child_id)
    return ChildSettingsOut.model_validate(child.settings)

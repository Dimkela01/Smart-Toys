"""Child profile logic (F-03, UC-03).

Limits come straight from the acceptance criteria: at most 5 children per parent, a
nickname of 1-20 characters, age 3-10, at most 5 interests, and an avatar that no sibling
already uses. The database enforces the same rules, so a race cannot slip past them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import content
from app.errors import api_error
from app.models import Child, ChildSettings, Parent
from app.models.children import MAX_CHILDREN_PER_PARENT
from app.schemas.children import ChildCreate, ChildUpdate
from app.services import audit


async def list_children(session: AsyncSession, *, parent_id: uuid.UUID) -> Sequence[Child]:
    result = await session.execute(
        select(Child).where(Child.parent_id == parent_id).order_by(Child.created_at)
    )
    return result.scalars().all()


async def get_child(session: AsyncSession, *, parent_id: uuid.UUID, child_id: uuid.UUID) -> Child:
    """404 for someone else's child, so ids cannot be probed."""
    result = await session.execute(select(Child).where(Child.id == child_id, Child.parent_id == parent_id))
    child = result.scalar_one_or_none()
    if child is None:
        raise api_error(404, "child_not_found", "That child profile does not exist.")
    return child


def _check_catalog(*, avatar_id: str | None, character_id: str | None) -> None:
    if avatar_id is not None and avatar_id not in content.avatar_ids():
        raise api_error(422, "unknown_avatar", "Pick one of the offered pictures.")
    if character_id is not None and character_id not in content.character_ids():
        raise api_error(422, "unknown_character", "Pick one of the offered characters.")


async def _avatar_is_taken(
    session: AsyncSession, *, parent_id: uuid.UUID, avatar_id: str, exclude: uuid.UUID | None = None
) -> bool:
    query = select(Child.id).where(Child.parent_id == parent_id, Child.avatar_id == avatar_id)
    if exclude is not None:
        query = query.where(Child.id != exclude)
    return (await session.execute(query)).first() is not None


async def create_child(session: AsyncSession, *, parent: Parent, data: ChildCreate) -> Child:
    count = await session.scalar(select(func.count()).select_from(Child).where(Child.parent_id == parent.id))
    if (count or 0) >= MAX_CHILDREN_PER_PARENT:
        raise api_error(
            409,
            "child_limit_reached",
            f"A family can have at most {MAX_CHILDREN_PER_PARENT} child profiles.",
        )

    character_id = data.character_id or content.default_character_id()
    _check_catalog(avatar_id=data.avatar_id, character_id=character_id)
    if await _avatar_is_taken(session, parent_id=parent.id, avatar_id=data.avatar_id):
        raise api_error(409, "avatar_taken", "Another child in the family already has that picture.")

    child = Child(
        parent_id=parent.id,
        nickname=data.nickname,
        age=data.age,
        language=data.language,
        interests=list(data.interests),
        avatar_id=data.avatar_id,
        character_id=character_id,
    )
    session.add(child)
    try:
        await session.flush()
    except IntegrityError as error:  # two tabs picking the same picture at once
        await session.rollback()
        raise api_error(
            409, "avatar_taken", "Another child in the family already has that picture."
        ) from error

    # settings are created with the child, using the UC-04 defaults
    session.add(ChildSettings(child_id=child.id, **ChildSettings.defaults()))
    await audit.record(
        session,
        actor_type="parent",
        actor_id=parent.id,
        action="child.created",
        target=f"child:{child.id}",
    )
    await session.flush()
    await session.refresh(child)
    return child


async def update_child(session: AsyncSession, *, parent: Parent, child: Child, data: ChildUpdate) -> Child:
    fields = data.model_dump(exclude_unset=True)
    _check_catalog(avatar_id=fields.get("avatar_id"), character_id=fields.get("character_id"))

    new_avatar = fields.get("avatar_id")
    changing_avatar = new_avatar is not None and new_avatar != child.avatar_id
    if changing_avatar and await _avatar_is_taken(
        session, parent_id=parent.id, avatar_id=str(new_avatar), exclude=child.id
    ):
        raise api_error(409, "avatar_taken", "Another child in the family already has that picture.")

    for key, value in fields.items():
        setattr(child, key, value)

    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise api_error(
            409, "avatar_taken", "Another child in the family already has that picture."
        ) from error

    await audit.record(
        session,
        actor_type="parent",
        actor_id=parent.id,
        action="child.updated",
        target=f"child:{child.id}",
    )
    await session.flush()
    await session.refresh(child)
    return child


async def delete_child(session: AsyncSession, *, parent: Parent, child: Child) -> None:
    """Removes the child and everything attached to it by cascade (UC-10)."""
    child_id = child.id
    await session.delete(child)
    await audit.record(
        session,
        actor_type="parent",
        actor_id=parent.id,
        action="child.deleted",
        target=f"child:{child_id}",
    )
    await session.flush()

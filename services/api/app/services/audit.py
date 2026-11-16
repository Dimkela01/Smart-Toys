"""Audit log helper.

Records who did what, never any personal content (DATA_MODEL.md §2.1). `target` holds an
id or a short machine-readable label such as "child:<uuid>" or "settings".
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

ActorType = Literal["parent", "admin", "system"]


async def record(
    session: AsyncSession,
    *,
    actor_type: ActorType,
    action: str,
    actor_id: uuid.UUID | None = None,
    target: str | None = None,
) -> None:
    session.add(AuditLog(actor_type=actor_type, actor_id=actor_id, action=action, target=target))
    await session.flush()

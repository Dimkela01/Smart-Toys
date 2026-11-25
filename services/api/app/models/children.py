"""Child profiles and their settings (DATA_MODEL.md §2.2).

Settings rows are created together with the child, using the UC-04 defaults. The screen
that edits them is M5; M1 only shows them read-only at the end of the add-child wizard.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, updated_at_column, uuid_pk

if TYPE_CHECKING:
    from app.models.accounts import Parent

#: Activity keys (CONTENT.md); all enabled by default (UC-04).
ACTIVITIES = ("why", "story", "numbers", "english")

MAX_CHILDREN_PER_PARENT = 5
MAX_INTERESTS = 5
MAX_BLOCKED_TOPICS = 20
DAILY_LIMIT_CHOICES = (10, 20, 30, 45, 60)

DEFAULT_ACTIVITIES_ENABLED: dict[str, bool] = dict.fromkeys(ACTIVITIES, True)
DEFAULT_DAILY_LIMIT_MIN = 20
DEFAULT_ALLOWED_FROM = time(7, 0)
DEFAULT_ALLOWED_TO = time(20, 30)


class Child(Base):
    __tablename__ = "children"

    id: Mapped[uuid.UUID] = uuid_pk()
    parent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: nickname, never a full name (UC-03)
    nickname: Mapped[str] = mapped_column(String(20), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    #: the server default is added by the M2 migration; see app/models/conversation.py
    interests: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    avatar_id: Mapped[str] = mapped_column(String(32), nullable=False)
    character_id: Mapped[str] = mapped_column(String(32), nullable=False)
    #: whether the "parents can see" line has been said (SAFETY.md §8, used from M2)
    first_session_done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = created_at_column()

    parent: Mapped[Parent] = relationship(back_populates="children")
    settings: Mapped[ChildSettings] = relationship(
        back_populates="child",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("age >= 3 and age <= 10", name="age_in_range"),
        CheckConstraint("char_length(nickname) between 1 and 20", name="nickname_length"),
        CheckConstraint("language in ('sr','en')", name="language_supported"),
        CheckConstraint("jsonb_array_length(interests) <= 5", name="interests_max_5"),
        CheckConstraint("avatar_id <> ''", name="avatar_id_present"),
        # UC-03 AC: avatar pictures are unique within a family
        UniqueConstraint("parent_id", "avatar_id", name="uq_children_parent_id_avatar_id"),
        {"comment": "Child profiles; no credentials, children sign in by picture (D4)"},
    )


class ChildSettings(Base):
    __tablename__ = "child_settings"

    child_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("children.id", ondelete="CASCADE"), primary_key=True
    )
    activities_enabled: Mapped[dict[str, bool]] = mapped_column(
        JSONB, nullable=False, default=lambda: dict(DEFAULT_ACTIVITIES_ENABLED)
    )
    blocked_topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    daily_limit_min: Mapped[int] = mapped_column(Integer, nullable=False, default=DEFAULT_DAILY_LIMIT_MIN)
    allowed_from: Mapped[time] = mapped_column(Time, nullable=False, default=DEFAULT_ALLOWED_FROM)
    allowed_to: Mapped[time] = mapped_column(Time, nullable=False, default=DEFAULT_ALLOWED_TO)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: full transcripts are off by default (D3, UC-04)
    transcripts_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alerts_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = updated_at_column()

    child: Mapped[Child] = relationship(back_populates="settings")

    __table_args__ = (
        CheckConstraint("daily_limit_min in (10,20,30,45,60)", name="daily_limit_choices"),
        CheckConstraint("jsonb_array_length(blocked_topics) <= 20", name="blocked_topics_max_20"),
    )

    @staticmethod
    def defaults() -> dict[str, Any]:
        """UC-04 defaults, applied when a child profile is created."""
        return {
            "activities_enabled": dict(DEFAULT_ACTIVITIES_ENABLED),
            "blocked_topics": [],
            "daily_limit_min": DEFAULT_DAILY_LIMIT_MIN,
            "allowed_from": DEFAULT_ALLOWED_FROM,
            "allowed_to": DEFAULT_ALLOWED_TO,
            "memory_enabled": True,
            "transcripts_visible": False,
            "alerts_email": True,
        }

"""Account tables (DATA_MODEL.md §2.1).

Three columns are not named in DATA_MODEL.md §2.1 but are needed to implement the
acceptance criteria; they are listed under "Assumptions" in the M1 report:

- `parents.token_version`  — bumped on password reset so old reset links and all issued
  tokens stop working (UC-02 AC "reset invalidates all sessions").
- `refresh_tokens.token_hash` — the refresh token itself is never stored, only its hash.
- `refresh_tokens.child_mode_at` — set while the device is locked in child mode, so the
  refresh endpoint cannot hand a parent session back without the PIN (UC-05 AC, UC-21).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, uuid_pk

if TYPE_CHECKING:
    from app.models.children import Child

USER_TYPES = ("parent", "admin")
CONSENT_TYPES = ("terms", "privacy", "pilot_research")
ACTOR_TYPES = ("parent", "admin", "system")


class Parent(Base):
    __tablename__ = "parents"

    id: Mapped[uuid.UUID] = uuid_pk()
    # stored lower-cased; uniqueness is therefore case-insensitive
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(2), nullable=False, default="sr")
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = created_at_column()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    children: Mapped[list[Child]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    consents: Mapped[list[Consent]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    __table_args__ = (CheckConstraint("locale in ('sr','en')", name="locale_supported"),)

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def has_pin(self) -> bool:
        return self.pin_hash is not None


class Consent(Base):
    """One row per consent given at registration (F-02, UC-01 AC)."""

    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = uuid_pk()
    parent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    consent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted_at: Mapped[datetime] = created_at_column()
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    parent: Mapped[Parent] = relationship(back_populates="consents")

    __table_args__ = (
        CheckConstraint("consent_type in ('terms','privacy','pilot_research')", name="consent_type_known"),
    )


class Admin(Base):
    """Team account: email + password + TOTP (SPEC.md §3)."""

    __tablename__ = "admins"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret_enc: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    created_at: Mapped[datetime] = created_at_column()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_type: Mapped[str] = mapped_column(String(16), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    child_mode_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("user_type in ('parent','admin')", name="user_type_known"),
        Index("ix_refresh_tokens_user_id_device_id", "user_id", "device_id"),
    )


class AuditLog(Base):
    """Who did what, never what was said (DATA_MODEL.md §2.1: no personal content)."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("actor_type in ('parent','admin','system')", name="actor_type_known"),
        Index("ix_audit_log_actor_id_created_at", "actor_id", "created_at"),
    )

"""M1 skeleton: accounts, consents, admins, refresh tokens, audit log, children, settings

Covers DATA_MODEL.md §2.1 and §2.2 only. Conversation, memory and evaluation tables
(§2.3-§2.5) are created by the milestones that use them.

Revision ID: 0001_m1_skeleton
Revises:
Create Date: 2026-11-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_m1_skeleton"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "parents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pin_hash", sa.String(length=255), nullable=True),
        sa.Column("locale", sa.String(length=2), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("locale in ('sr','en')", name="ck_parents_locale_supported"),
        sa.PrimaryKeyConstraint("id", name="pk_parents"),
        sa.UniqueConstraint("email", name="uq_parents_email"),
    )

    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.Column("consent_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "consent_type in ('terms','privacy','pilot_research')",
            name="ck_consents_consent_type_known",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["parents.id"],
            name="fk_consents_parent_id_parents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_consents"),
    )
    op.create_index("ix_consents_parent_id", "consents", ["parent_id"])

    op.create_table(
        "admins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("totp_secret_enc", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_admins"),
        sa.UniqueConstraint("email", name="uq_admins_email"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("user_type", sa.String(length=16), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("child_mode_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("user_type in ('parent','admin')", name="ck_refresh_tokens_user_type_known"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id_device_id", "refresh_tokens", ["user_id", "device_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("actor_type in ('parent','admin','system')", name="ck_audit_log_actor_type_known"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_actor_id_created_at", "audit_log", ["actor_id", "created_at"])

    op.create_table(
        "children",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.Column("nickname", sa.String(length=20), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("interests", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("avatar_id", sa.String(length=32), nullable=False),
        sa.Column("character_id", sa.String(length=32), nullable=False),
        sa.Column("first_session_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("age >= 3 and age <= 10", name="ck_children_age_in_range"),
        sa.CheckConstraint("avatar_id <> ''", name="ck_children_avatar_id_present"),
        sa.CheckConstraint("char_length(nickname) between 1 and 20", name="ck_children_nickname_length"),
        sa.CheckConstraint("jsonb_array_length(interests) <= 5", name="ck_children_interests_max_5"),
        sa.CheckConstraint("language in ('sr','en')", name="ck_children_language_supported"),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["parents.id"],
            name="fk_children_parent_id_parents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_children"),
        sa.UniqueConstraint("parent_id", "avatar_id", name="uq_children_parent_id_avatar_id"),
        comment="Child profiles; no credentials, children sign in by picture (D4)",
    )
    op.create_index("ix_children_parent_id", "children", ["parent_id"])

    op.create_table(
        "child_settings",
        sa.Column("child_id", sa.Uuid(), nullable=False),
        sa.Column("activities_enabled", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("blocked_topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("daily_limit_min", sa.Integer(), nullable=False),
        sa.Column("allowed_from", sa.Time(), nullable=False),
        sa.Column("allowed_to", sa.Time(), nullable=False),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False),
        sa.Column("transcripts_visible", sa.Boolean(), nullable=False),
        sa.Column("alerts_email", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "daily_limit_min in (10,20,30,45,60)", name="ck_child_settings_daily_limit_choices"
        ),
        sa.CheckConstraint(
            "jsonb_array_length(blocked_topics) <= 20",
            name="ck_child_settings_blocked_topics_max_20",
        ),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["children.id"],
            name="fk_child_settings_child_id_children",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("child_id", name="pk_child_settings"),
    )


def downgrade() -> None:
    op.drop_table("child_settings")
    op.drop_index("ix_children_parent_id", table_name="children")
    op.drop_table("children")
    op.drop_index("ix_audit_log_actor_id_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_refresh_tokens_user_id_device_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("admins")
    op.drop_index("ix_consents_parent_id", table_name="consents")
    op.drop_table("consents")
    op.drop_table("parents")

"""M2 voice loop: sessions, turns, per-turn metrics

Covers DATA_MODEL.md §2.3 apart from events and alerts, which belong to the safety
layer and arrive with M3.

Nothing here can hold audio: DATA_MODEL.md §6 says audio is never stored, so there is no
column for it. The turn texts are nullable because the retention job (M5) blanks them at
delete_after and keeps the row - turn_metrics lives twelve months and would go with it.

Revision ID: 0002_m2_conversation
Revises: 0001_m1_skeleton
Create Date: 2026-11-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_m2_conversation"
down_revision: str | None = "0001_m1_skeleton"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("child_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=16), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column(
            "activities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column(
            "topic_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("summary_model_id", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "end_reason is null or end_reason in ('idle','exit','limit','hours')",
            name=op.f("ck_sessions_end_reason_known"),
        ),
        sa.CheckConstraint(
            "duration_s is null or duration_s >= 0", name=op.f("ck_sessions_duration_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["child_id"], ["children.id"], name=op.f("fk_sessions_child_id_children"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
    )
    op.create_index(op.f("ix_sessions_child_id"), "sessions", ["child_id"], unique=False)
    op.create_table(
        "turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("child_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("child_text", sa.Text(), nullable=True),
        sa.Column("bruno_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("router_decision", sa.String(length=24), nullable=False),
        sa.Column("fixed_response_id", sa.String(length=32), nullable=True),
        sa.Column("activity", sa.String(length=16), nullable=True),
        sa.Column("activity_state_after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("interrupted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("profile", sa.String(length=8), nullable=False),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("language in ('sr','en')", name=op.f("ck_turns_language_supported")),
        sa.CheckConstraint("profile in ('server','device')", name=op.f("ck_turns_profile_known")),
        sa.CheckConstraint(
            "router_decision in ('llm','fixed','blocked_by_parent','urgent','low_confidence')",
            name=op.f("ck_turns_router_decision_known"),
        ),
        sa.ForeignKeyConstraint(
            ["child_id"], ["children.id"], name=op.f("fk_turns_child_id_children"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_turns_session_id_sessions"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_turns")),
    )
    op.create_index(op.f("ix_turns_child_id"), "turns", ["child_id"], unique=False)
    op.create_index(op.f("ix_turns_delete_after"), "turns", ["delete_after"], unique=False)
    op.create_index(op.f("ix_turns_session_id"), "turns", ["session_id"], unique=False)
    op.create_table(
        "turn_metrics",
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("stt_ms", sa.Integer(), nullable=True),
        sa.Column("stt_confidence", sa.Float(), nullable=True),
        sa.Column("router_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens_cached", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("prefill_tps", sa.Float(), nullable=True),
        sa.Column("decode_tps", sa.Float(), nullable=True),
        sa.Column("llm_total_ms", sa.Integer(), nullable=True),
        sa.Column("tts_first_ms", sa.Integer(), nullable=True),
        sa.Column("first_audio_ms", sa.Integer(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.Column("llm_rss_mb", sa.Integer(), nullable=True),
        sa.Column("gpu_mem_mb", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("error_code", sa.String(length=24), nullable=True),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turns.id"], name=op.f("fk_turn_metrics_turn_id_turns"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("turn_id", name=op.f("pk_turn_metrics")),
    )

    # children.interests has the same gap: a Python-side default only covers inserts made
    # through SQLAlchemy, and from M5 the retention and summary jobs write SQL. Fixed here
    # rather than by editing 0001, which has already been applied.
    op.alter_column("children", "interests", server_default=sa.text("'[]'::jsonb"))


def downgrade() -> None:
    op.alter_column("children", "interests", server_default=None)
    op.drop_table("turn_metrics")
    op.drop_index(op.f("ix_turns_session_id"), table_name="turns")
    op.drop_index(op.f("ix_turns_delete_after"), table_name="turns")
    op.drop_index(op.f("ix_turns_child_id"), table_name="turns")
    op.drop_table("turns")
    op.drop_index(op.f("ix_sessions_child_id"), table_name="sessions")
    op.drop_table("sessions")

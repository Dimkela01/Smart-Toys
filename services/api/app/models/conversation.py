"""Sessions, turns and per-turn metrics (DATA_MODEL.md §2.3).

Three rules from docs/CLAUDE.md §2 and DATA_MODEL.md §6 are built into the shapes here:

* **Audio is never stored.** There is no column for it anywhere, and no file is written.
* **Turn text lives 30 days, metrics live 12 months.** So the nightly retention job (M5)
  blanks `child_text` and `bruno_text` at `delete_after` and keeps the row: deleting the
  turn would take its metrics with it, and the metrics carry no text at all.
* **Metrics are admin-only.** Nothing in `turn_metrics` is ever shown to a parent or a
  child; it exists for the benchmark and the admin dashboard (EVALUATION.md §4.1).

`events` and `alerts` (§2.3) belong to the safety layer and arrive with M3.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, uuid_pk

if TYPE_CHECKING:
    from app.models.children import Child

#: an empty JSON array, for the list columns below
EMPTY_JSON_ARRAY = text("'[]'::jsonb")

#: why a session ended (§2.3). `idle` is the child walking away, `exit` the parent PIN,
#: `limit` the daily minutes, `hours` the allowed-hours window closing.
SESSION_END_REASONS = ("idle", "exit", "limit", "hours")

#: what the router decided (SAFETY.md §2). M2 only ever writes "llm": the router is M3.
ROUTER_DECISIONS = ("llm", "fixed", "blocked_by_parent", "urgent", "low_confidence")

#: why a turn failed, if it did (EVALUATION.md §4.1). Kept short and stable so the admin
#: dashboard can group by it; the child only ever hears a fallback line.
TURN_ERROR_CODES = (
    "stt_empty",
    "stt_failed",
    "llm_timeout",
    "llm_failed",
    "tts_failed",
    "filter_blocked",
    "queue_timeout",
    "interrupted",
)


class Session(Base):
    """One sitting with the toy."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    child_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("children.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = created_at_column()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: which activities were used, for the parent summary (M5). The server default
    #: matters: the retention and summary jobs write SQL, and a Python-side default only
    #: covers inserts that go through SQLAlchemy.
    activities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=EMPTY_JSON_ARRAY
    )
    #: written by the summary job in M5, shown to the parent
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=EMPTY_JSON_ARRAY
    )
    #: which model wrote the summary, so a bad summary can be traced to it (F-20)
    summary_model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    child: Mapped[Child] = relationship()
    turns: Mapped[list[Turn]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Turn.created_at"
    )

    __table_args__ = (
        CheckConstraint(
            "end_reason is null or end_reason in ('idle','exit','limit','hours')",
            name="end_reason_known",
        ),
        CheckConstraint("duration_s is null or duration_s >= 0", name="duration_not_negative"),
    )


class Turn(Base):
    """One exchange: what the child said and what the toy answered."""

    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: denormalised so the retention job and the parent's transcript view can both work
    #: from the child without joining through sessions
    child_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("children.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = created_at_column()
    #: nullable because the retention job blanks them at delete_after, keeping the row
    child_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    bruno_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    router_decision: Mapped[str] = mapped_column(String(24), nullable=False)
    #: set when the answer came from a fixed response instead of the model (M3)
    fixed_response_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    activity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    activity_state_after: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    #: the child pressed the paw again while the answer was playing (barge-in)
    interrupted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    #: which model and prompt produced this answer, so any answer can be traced (F-20)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile: Mapped[str] = mapped_column(String(8), nullable=False)
    #: when the texts above must be blanked (DATA_MODEL.md §6; the job is M5)
    delete_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    session: Mapped[Session] = relationship(back_populates="turns")
    metrics: Mapped[TurnMetrics | None] = relationship(
        back_populates="turn", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        CheckConstraint("language in ('sr','en')", name="language_supported"),
        CheckConstraint("profile in ('server','device')", name="profile_known"),
        CheckConstraint(
            "router_decision in ('llm','fixed','blocked_by_parent','urgent','low_confidence')",
            name="router_decision_known",
        ),
    )


class TurnMetrics(Base):
    """What one turn cost (EVALUATION.md §4.1). Admin-only, and holds no text.

    Every column is nullable: a turn that failed in the middle still deserves the
    measurements it did reach, and that is exactly the turn worth looking at.
    """

    __tablename__ = "turn_metrics"

    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("turns.id", ondelete="CASCADE"), primary_key=True
    )
    stt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stt_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    router_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens_cached: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prefill_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    decode_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tts_first_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: the headline number (NFR-01): turn.end received -> first audio chunk sent
    first_audio_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_rss_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: null on this hardware: Docker on macOS has no GPU to measure
    gpu_mem_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    error_code: Mapped[str | None] = mapped_column(String(24), nullable=True)

    turn: Mapped[Turn] = relationship(back_populates="metrics")

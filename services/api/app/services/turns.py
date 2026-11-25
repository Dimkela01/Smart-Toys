"""Storing sessions, turns and metrics (DATA_MODEL.md §2.3, §6).

Nothing here touches audio. The texts written are the transcript and the answer, which
the parent may read later if transcripts are on (M5); the metrics carry no text at all
and are admin-only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Language, Profile, settings
from app.models import Session, Turn, TurnMetrics
from app.orchestrator import prompt
from app.orchestrator.turn import Metrics

#: how many past turns the prompt may use (DATA_MODEL.md §3.1)
HISTORY_WINDOW = prompt.HISTORY_MAX_TURNS


async def start_session(session: AsyncSession, *, child_id: uuid.UUID) -> Session:
    row = Session(child_id=child_id, activities=[], topic_tags=[])
    session.add(row)
    await session.flush()
    return row


async def end_session(session: AsyncSession, row: Session, *, reason: str) -> None:
    now = datetime.now(UTC)
    row.ended_at = now
    row.end_reason = reason
    row.duration_s = max(0, int((now - row.started_at).total_seconds()))
    await session.flush()


async def recent_history(
    session: AsyncSession, *, child_id: uuid.UUID, session_id: uuid.UUID
) -> list[prompt.Turn]:
    """The last turns of *this* session, oldest first (§3.1).

    Deliberately scoped to the session: memory across sessions is a parent-controlled
    feature with its own table (M5), not something that leaks in through the history
    window. Turns whose text has been blanked by the retention job are skipped.
    """
    result = await session.execute(
        select(Turn)
        .where(Turn.session_id == session_id, Turn.child_id == child_id)
        .order_by(Turn.created_at.desc())
        .limit(HISTORY_WINDOW)
    )
    rows = list(result.scalars())
    rows.reverse()
    return [
        prompt.Turn(child_text=row.child_text, answer_text=row.bruno_text)
        for row in rows
        if row.child_text and row.bruno_text
    ]


async def record_turn(
    session: AsyncSession,
    *,
    session_row: Session,
    child_id: uuid.UUID,
    language: Language,
    child_text: str | None,
    answer_text: str | None,
    metrics: Metrics,
    model_id: str | None = None,
    prompt_version: str | None = None,
    profile: Profile = "server",
    router_decision: str = "llm",
    interrupted: bool = False,
) -> Turn:
    """One row per turn, successful or not. A failed turn is the interesting one."""
    turn = Turn(
        session_id=session_row.id,
        child_id=child_id,
        child_text=child_text,
        bruno_text=answer_text,
        language=language,
        router_decision=router_decision,
        interrupted=interrupted,
        model_id=model_id,
        prompt_version=prompt_version,
        profile=profile,
        delete_after=datetime.now(UTC) + timedelta(days=settings.transcript_retention_days),
    )
    session.add(turn)
    await session.flush()
    session.add(
        TurnMetrics(
            turn_id=turn.id,
            stt_ms=metrics.stt_ms,
            stt_confidence=metrics.stt_confidence,
            prompt_tokens=metrics.prompt_tokens,
            prompt_tokens_cached=metrics.prompt_tokens_cached,
            output_tokens=metrics.output_tokens,
            ttft_ms=metrics.ttft_ms,
            prefill_tps=metrics.prefill_tps,
            decode_tps=metrics.decode_tps,
            llm_total_ms=metrics.llm_total_ms,
            tts_first_ms=metrics.tts_first_ms,
            first_audio_ms=metrics.first_audio_ms,
            total_ms=metrics.total_ms,
            truncated=metrics.truncated,
            error_code=metrics.error_code,
        )
    )
    await session.flush()
    return turn

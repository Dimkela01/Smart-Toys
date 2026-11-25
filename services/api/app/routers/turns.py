"""The turn WebSocket (ARCHITECTURE.md §7.2).

    client -> server   turn.start, binary PCM frames, turn.end, turn.cancel,
                       activity.select, choice.select
    server -> client   state, binary WAV frames, turn.done, limit, error

**The child client never receives model text** (§7.2): the only things sent are a state
name, audio, and an error code the client turns into one of its own bundled lines.

Authentication uses the WebSocket subprotocol rather than a query parameter:

    new WebSocket(url, ["bearer", token])

A browser cannot set an Authorization header on a WebSocket, and a token in the query
string ends up in access logs and browser history. The subprotocol is sent in the
handshake headers instead, which is the same place the header would have been.

Binary frames carry a small JSON header, because one connection interleaves the audio of
one turn with whatever the next turn starts sending after a barge-in, and the client has
to be able to drop frames from a turn it has abandoned:

    client -> server   [4-byte big-endian sequence number][PCM16 16 kHz mono]
    server -> client   [4-byte big-endian header length][JSON header][WAV]
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app import content
from app.config import Language, settings
from app.db import session_scope
from app.inference import Inference
from app.models import Child, Session
from app.orchestrator import prompt, turn
from app.redis_client import get_redis
from app.security import tokens
from app.services import auth as auth_service
from app.services import children as children_service
from app.services import turns as turn_service

logger = logging.getLogger("app.turns")

router = APIRouter(tags=["turns"])

#: close codes. 1008 is "policy violation", which is what an unusable token is.
CLOSE_UNAUTHENTICATED = 1008
CLOSE_GOING_AWAY = 1001

#: the subprotocol the client offers alongside its token
BEARER = "bearer"

#: how long to wait for the client to say anything before assuming it is gone. The toy
#: screen sends a turn or a ping well inside this.
IDLE_TIMEOUT_S = 300.0


@dataclass
class Running:
    """A turn in flight, and whether it has already written its row.

    A cancelled task cannot store anything: the first `await` in its cleanup is itself
    cancelled, so an interrupted turn went silently unrecorded. The canceller writes that
    row instead - which is also the only place that knows the turn was interrupted rather
    than merely failed.
    """

    #: set immediately after construction, because the turn needs this object
    task: asyncio.Task[None] | None = None
    stored: bool = False


def _token_from(websocket: WebSocket) -> str | None:
    offered = [str(item) for item in (websocket.scope.get("subprotocols") or [])]
    if len(offered) >= 2 and offered[0] == BEARER:
        return offered[1]
    return None


async def _authenticate(websocket: WebSocket, session: AsyncSession) -> Child | None:
    """Resolve the child session token to a child, or None if it cannot be trusted.

    The same four checks as the REST dependency in app/deps.py: the right token type, a
    parent that still exists and is fully set up, child mode still active on *this*
    device, and a child that belongs to that parent.
    """
    raw = _token_from(websocket)
    if raw is None:
        return None
    try:
        payload = tokens.decode_token(raw, expected=tokens.CHILD_SESSION)
    except tokens.TokenError as error:
        logger.info("ws rejected: %s", error.code)
        return None

    parent = await auth_service.get_parent(session, tokens.subject_of(payload))
    if parent is None or not parent.is_verified or not parent.has_pin:
        return None
    device_id = str(payload.get("did", ""))
    # leaving child mode or logging out clears the flag, which invalidates the token
    if not await auth_service.device_is_in_child_mode(session, parent_id=parent.id, device_id=device_id):
        logger.info("ws rejected: child mode is no longer active on this device")
        return None
    try:
        return await children_service.get_child(
            session, parent_id=parent.id, child_id=tokens.child_of(payload)
        )
    except HTTPException:
        # the profile was deleted while the toy screen was open
        logger.info("ws rejected: the child in the token no longer exists")
        return None


async def _within_rate_limit(child_id: uuid.UUID) -> bool:
    """ARCHITECTURE.md §9: turns 20/min per child. Fails open, like the auth limiter."""
    window = int(time.time() // 60)
    key = f"rl:turns:{child_id}:{window}"
    try:
        client = get_redis()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 60)
    except RedisError as error:
        logger.error("turn rate limit check failed, allowing: %s", type(error).__name__)
        return True
    return count <= settings.turn_rate_limit_per_minute


def _character_for(child: Child) -> prompt.Character:
    """Block 2 from content/characters.json, in the child's language."""
    language = child.language
    for item in content.characters():
        if item.get("id") == child.character_id:
            names = item.get("name") or {}
            personalities = item.get("personality") or {}
            return prompt.Character(
                name=str(names.get(language) or names.get("en") or child.character_id),
                personality=str(personalities.get(language) or ""),
            )
    # the picker only offers characters from the catalog, so this is a content error
    logger.error("child %s refers to unknown character %s", child.id, child.character_id)
    return prompt.Character(name="Bruno", personality="")


class Channel:
    """Everything that goes to the client, serialised through one lock.

    The receive loop and the running turn both send, so without the lock a `turn.done`
    could overtake the audio frame before it.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._lock = asyncio.Lock()

    async def event(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            await self._websocket.send_json(payload)

    async def state(self, state: str) -> None:
        await self.event({"type": "state", "state": state})

    async def error(self, code: str) -> None:
        """A code only: the child screen never shows text (NFR-09, §7.2)."""
        await self.event({"type": "error", "code": code})

    async def audio(self, *, turn_id: str, seq: int, wav: bytes) -> None:
        header = json.dumps({"turn_id": turn_id, "seq": seq}).encode()
        async with self._lock:
            await self._websocket.send_bytes(struct.pack(">I", len(header)) + header + wav)


@router.websocket("/ws/turns")
async def turns(websocket: WebSocket) -> None:
    async with session_scope() as session:
        child = await _authenticate(websocket, session)
        if child is None:
            await websocket.close(code=CLOSE_UNAUTHENTICATED)
            return
        child_id = child.id
        session_row = await turn_service.start_session(session, child_id=child.id)
        session_id = session_row.id
        language: Language = child.language  # type: ignore[assignment]
        context = turn.TurnContext(
            child=prompt.Child(
                nickname=child.nickname,
                age=child.age,
                language=language,
                interests=tuple(child.interests or ()),
            ),
            character=_character_for(child),
        )

    await websocket.accept(subprotocol=BEARER if _token_from(websocket) else None)
    channel = Channel(websocket)
    inference = Inference.create()
    end_reason = "idle"

    logger.info("ws open: child %s, session %s", child_id, session_id)
    try:
        end_reason = await _conversation(websocket, channel, inference, context, child_id, session_id)
    except WebSocketDisconnect:
        end_reason = "idle"
    finally:
        await inference.aclose()
        async with session_scope() as session:
            row = await session.get(Session, session_id)
            if row is not None and row.ended_at is None:
                await turn_service.end_session(session, row, reason=end_reason)
        logger.info("ws closed: session %s (%s)", session_id, end_reason)


async def _conversation(
    websocket: WebSocket,
    channel: Channel,
    inference: Inference,
    context: turn.TurnContext,
    child_id: uuid.UUID,
    session_id: uuid.UUID,
) -> str:
    """Receive loop. Returns the session's end reason."""
    audio = bytearray()
    recording = False
    truncated = False
    running: Running | None = None

    async def abandon(current: Running | None) -> None:
        """Cancel a turn in flight and record it, exactly once."""
        if current is None or current.task is None:
            return
        current.task.cancel()
        try:
            await current.task
        except asyncio.CancelledError:
            pass
        except Exception as error:  # the turn was going to fail anyway
            logger.warning("abandoned turn ended with %s", type(error).__name__)
        if not current.stored:
            current.stored = True
            await _store(
                session_id,
                child_id,
                context,
                turn.Metrics(error_code="interrupted"),
                None,
                None,
                interrupted=True,
            )

    while True:
        try:
            message = await asyncio.wait_for(websocket.receive(), timeout=IDLE_TIMEOUT_S)
        except TimeoutError:
            return "idle"
        if message["type"] == "websocket.disconnect":
            await abandon(running)
            return "idle"

        if (chunk := message.get("bytes")) is not None:
            if not recording or len(chunk) <= 4:
                continue
            # the sequence number is the client's; frames arrive in order on one
            # connection, so it is only used to notice a gap
            if len(audio) + len(chunk) - 4 > turn.MAX_AUDIO_BYTES:
                truncated = True
                keep = turn.MAX_AUDIO_BYTES - len(audio)
                if keep > 0:
                    audio.extend(chunk[4 : 4 + keep])
                continue
            audio.extend(chunk[4:])
            continue

        text = message.get("text")
        if text is None:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            logger.info("ws sent a message that is not JSON (%d bytes)", len(text))
            continue

        kind = event.get("type")
        if kind == "turn.start":
            # barge-in: the child pressed again while the answer was still playing
            await abandon(running)
            running = None
            audio = bytearray()
            recording = True
            truncated = False
            await channel.state("listening")
        elif kind == "turn.end":
            if not recording:
                continue
            recording = False
            if not await _within_rate_limit(child_id):
                await channel.error("rate_limited")
                continue
            if truncated:
                logger.info("a press ran past the %d ms cap", turn.MAX_AUDIO_MS)
            started = Running()
            started.task = asyncio.create_task(
                _run_turn(channel, inference, context, bytes(audio), child_id, session_id, started)
            )
            running = started
            audio = bytearray()
        elif kind == "turn.cancel":
            recording = False
            audio = bytearray()
            await abandon(running)
            running = None
            await channel.state(turn.STATE_IDLE)
        elif kind in {"activity.select", "choice.select"}:
            # the activity engine is M4; acknowledged so the client can be written once
            logger.info("activity message %s received before M4", kind)
            await channel.state(turn.STATE_IDLE)
        elif kind == "ping":
            await channel.event({"type": "pong"})


async def _run_turn(
    channel: Channel,
    inference: Inference,
    context: turn.TurnContext,
    audio: bytes,
    child_id: uuid.UUID,
    session_id: uuid.UUID,
    running: Running,
) -> None:
    """One turn, start to finish.

    On barge-in this task is cancelled, and it deliberately writes nothing on the way
    out: the canceller does that (see Running).
    """
    turn_id = uuid.uuid4().hex
    async with session_scope() as session:
        context = turn.TurnContext(
            child=context.child,
            character=context.character,
            history=await turn_service.recent_history(session, child_id=child_id, session_id=session_id),
            profile=context.profile,
        )

    async for event in turn.run(inference, context, audio):
        if isinstance(event, turn.Thinking):
            await channel.state(turn.STATE_THINKING)
        elif isinstance(event, turn.Speaking):
            if event.seq == 1:
                await channel.state(turn.STATE_SPEAKING)
            await channel.audio(turn_id=turn_id, seq=event.seq, wav=event.wav)
        elif isinstance(event, turn.Failed):
            await channel.error(event.code)
            await channel.state(turn.STATE_IDLE)
            await _store(session_id, child_id, context, event.metrics, None, None)
            running.stored = True
            return
        elif isinstance(event, turn.Finished):
            # Store before announcing. The child has already heard the answer, so
            # `turn.done` is only bookkeeping - but a client that closes the moment it
            # hears it makes the receive loop cancel this task, and a cancelled task
            # cannot finish a write. Announcing last means the row is already safe, and
            # a cancellation during the write leaves `stored` false so the canceller
            # records the turn instead. Found by running a real socket: every turn
            # played correctly and `turns` stayed empty.
            await _store(
                session_id,
                child_id,
                context,
                event.metrics,
                event.child_text,
                event.answer_text,
                model_id=event.model_id,
                prompt_version=event.prompt_version,
            )
            running.stored = True
            await channel.event({"type": "turn.done", "turn_id": turn_id})
            await channel.state(turn.STATE_IDLE)
            return


async def _store(
    session_id: uuid.UUID,
    child_id: uuid.UUID,
    context: turn.TurnContext,
    metrics: turn.Metrics,
    child_text: str | None,
    answer_text: str | None,
    *,
    model_id: str | None = None,
    prompt_version: str | None = None,
    interrupted: bool = False,
) -> None:
    async with session_scope() as session:
        row = await session.get(Session, session_id)
        if row is None:  # pragma: no cover - the session is created before the socket opens
            return
        await turn_service.record_turn(
            session,
            session_row=row,
            child_id=child_id,
            language=context.language,
            child_text=child_text,
            answer_text=answer_text,
            metrics=metrics,
            model_id=model_id,
            prompt_version=prompt_version,
            profile=context.profile,
            interrupted=interrupted,
        )

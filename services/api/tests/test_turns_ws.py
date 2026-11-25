"""The turn WebSocket and the pipeline behind it (F-05, F-06, F-07, UC-11, UC-22).

No real socket and no real models: a scripted stand-in for the WebSocket drives the
protocol state machine, and the three inference services answer through an httpx
MockTransport. That covers what actually breaks - the order of messages, barge-in, the
caps, and what reaches the child - without needing 2 GB of weights in CI.

The rule these tests exist to defend: **the child client never receives model text**
(ARCHITECTURE.md §7.2). A failure is a code, and the client speaks its own audio.
"""

from __future__ import annotations

import asyncio
import io
import json
import struct
import wave
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.inference import Inference
from app.inference.clients import LanguageModelClient, SpeechToText, TextToSpeech
from app.models import Session, Turn, TurnMetrics
from app.orchestrator import turn
from app.routers import turns as ws
from tests.conftest import DEFAULT_PIN

CHILD_MODE = "/api/v1/child-mode"

#: 16 kHz mono PCM16; one second of quiet is plenty, since STT is mocked
ONE_SECOND = b"\x00\x01" * turn.SAMPLE_RATE


def _wav(seconds: float = 0.5, rate: int = 22050) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x01" * int(rate * seconds))
    return buffer.getvalue()


class FakeSocket:
    """Enough of starlette's WebSocket for the router, plus a script to replay."""

    def __init__(self, script: list[dict[str, Any]], *, token: str | None = None) -> None:
        self.scope: dict[str, Any] = {"subprotocols": ["bearer", token] if token else []}
        self._script = list(script)
        self.sent: list[dict[str, Any]] = []
        self.binary: list[tuple[dict[str, Any], bytes]] = []
        self.accepted_subprotocol: str | None = None
        self.close_code: int | None = None
        self._closed = asyncio.Event()

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_subprotocol = subprotocol

    async def close(self, code: int = 1000) -> None:
        self.close_code = code
        self._closed.set()

    async def receive(self) -> dict[str, Any]:
        if self._script:
            step = self._script.pop(0)
            # a step may ask for a pause, so a turn can get going before the next message
            if "sleep" in step:
                await asyncio.sleep(step["sleep"])
                return await self.receive()
            return step
        # nothing left to say: behave like a client that went away
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        size = struct.unpack(">I", payload[:4])[0]
        header = json.loads(payload[4 : 4 + size])
        self.binary.append((header, payload[4 + size :]))

    # --- assertions ---

    def events(self, kind: str) -> list[dict[str, Any]]:
        return [item for item in self.sent if item.get("type") == kind]

    def states(self) -> list[str]:
        return [str(item["state"]) for item in self.events("state")]

    def codes(self) -> list[str]:
        return [str(item["code"]) for item in self.events("error")]


def _frame(seq: int, pcm: bytes) -> dict[str, Any]:
    return {"type": "websocket.receive", "bytes": struct.pack(">I", seq) + pcm}


def _message(**payload: Any) -> dict[str, Any]:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def _inference(
    *,
    transcript: str = "Zasto je nebo plavo?",
    answer: str = "Nebo je plavo! Hoces da ti pricam o suncu?",
    stt_status: int = 200,
    tts_status: int = 200,
    llm_status: int = 200,
    no_speech: float = 0.01,
) -> Inference:
    """All three services behind one MockTransport, keyed by path."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/transcribe"):
            if stt_status != 200:
                return httpx.Response(stt_status, text="no")
            return httpx.Response(
                200,
                json={
                    "text": transcript,
                    "confidence": 0.8,
                    "no_speech_prob": no_speech,
                    "duration_ms": 1000,
                    "stt_ms": 120,
                    "model_id": "stt-under-test",
                },
            )
        if path.endswith("/synthesize"):
            if tts_status != 200:
                return httpx.Response(tts_status, text="no voice")
            return httpx.Response(
                200,
                content=_wav(),
                headers={"X-Sample-Rate": "22050", "X-Audio-Ms": "500", "X-Synth-Ms": "20"},
            )
        if path.endswith("/chat/completions"):
            if llm_status != 200:
                return httpx.Response(llm_status, text="busy")
            chunks = [
                f"data: {json.dumps({'choices': [{'delta': {'content': answer}}]})}\n\n",
                "data: "
                + json.dumps(
                    {
                        "choices": [{"delta": {}, "finish_reason": "stop"}],
                        "usage": {
                            "prompt_tokens": 300,
                            "completion_tokens": 12,
                            "prompt_tokens_details": {"cached_tokens": 280},
                        },
                    }
                )
                + "\n\n",
                "data: [DONE]\n\n",
            ]
            return httpx.Response(
                200, content="".join(chunks).encode(), headers={"Content-Type": "text/event-stream"}
            )
        raise AssertionError(f"unexpected request to {path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Inference(
        client=client,
        stt=SpeechToText(client),
        tts=TextToSpeech(client),
        llm=LanguageModelClient(client),
    )


async def _child_session(client: AsyncClient, parent_headers: dict[str, str]) -> str:
    """Register a child, enter child mode, pick the child: the token the toy screen holds."""
    created = await client.post(
        "/api/v1/children",
        json={
            "nickname": "Mila",
            "age": 5,
            "language": "sr",
            "interests": ["animals"],
            "avatar_id": "avatar-01",
            "character_id": "bear",
        },
        headers=parent_headers,
    )
    assert created.status_code == 201, created.text
    entered = await client.post(f"{CHILD_MODE}/enter", headers=parent_headers)
    assert entered.status_code == 200, entered.text
    mode_token = entered.json()["token"]
    selected = await client.post(
        f"{CHILD_MODE}/select",
        json={"child_id": created.json()["id"]},
        headers={"Authorization": f"Bearer {mode_token}"},
    )
    assert selected.status_code == 200, selected.text
    return str(selected.json()["token"])


async def _drive(script: list[dict[str, Any]], token: str, inference: Inference | None = None) -> FakeSocket:
    """Run the router against a scripted client."""
    socket = FakeSocket(script, token=token)
    bundle = inference or _inference()
    original = Inference.create
    Inference.create = staticmethod(lambda **_: bundle)  # type: ignore[method-assign]
    try:
        await ws.turns(socket)  # type: ignore[arg-type]
    finally:
        Inference.create = original  # type: ignore[method-assign]
    return socket


# --- authentication ----------------------------------------------------------------


async def test_a_connection_without_a_token_is_closed(client: AsyncClient) -> None:
    socket = FakeSocket([])
    await ws.turns(socket)  # type: ignore[arg-type]
    assert socket.close_code == ws.CLOSE_UNAUTHENTICATED
    assert socket.accepted_subprotocol is None, "nothing should be accepted"


async def test_a_parent_token_cannot_open_the_turn_socket(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    """The audiences are separate: a parent token is not a child session (§9)."""
    parent_token = parent_headers["Authorization"].removeprefix("Bearer ")
    socket = FakeSocket([], token=parent_token)
    await ws.turns(socket)  # type: ignore[arg-type]
    assert socket.close_code == ws.CLOSE_UNAUTHENTICATED


async def test_leaving_child_mode_closes_the_door_on_a_token_already_issued(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    token = await _child_session(client, parent_headers)
    exited = await client.post(
        f"{CHILD_MODE}/exit",
        json={"pin": DEFAULT_PIN},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exited.status_code == 200, exited.text
    socket = FakeSocket([], token=token)
    await ws.turns(socket)  # type: ignore[arg-type]
    assert socket.close_code == ws.CLOSE_UNAUTHENTICATED


async def test_a_valid_child_session_is_accepted_on_the_bearer_subprotocol(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    token = await _child_session(client, parent_headers)
    socket = await _drive([], token)
    assert socket.accepted_subprotocol == ws.BEARER
    assert socket.close_code is None


# --- one whole turn ----------------------------------------------------------------


async def test_a_held_paw_comes_back_as_audio_and_never_as_text(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    token = await _child_session(client, parent_headers)
    socket = await _drive(
        [
            _message(type="turn.start", turn_id_client="t1"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end", turn_id_client="t1"),
            {"sleep": 0.2},
        ],
        token,
    )

    assert socket.states()[:3] == ["listening", turn.STATE_THINKING, turn.STATE_SPEAKING]
    assert socket.events("turn.done"), "the turn must be reported as finished"
    assert socket.codes() == [], f"no error expected: {socket.codes()}"

    # two sentences in the mocked answer, so two audio frames, in order
    assert [header["seq"] for header, _ in socket.binary] == [1, 2]
    assert all(audio.startswith(b"RIFF") for _, audio in socket.binary)
    assert len({header["turn_id"] for header, _ in socket.binary}) == 1

    # the answer text must appear nowhere in anything sent to the child
    everything = json.dumps(socket.sent)
    for word in ("Nebo", "plavo", "sunc", "Zasto"):
        assert word not in everything, f"{word!r} reached the child client"


async def test_the_turn_and_its_metrics_are_stored(
    client: AsyncClient,
    parent_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = await _child_session(client, parent_headers)
    await _drive(
        [
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.2},
        ],
        token,
    )

    async with session_factory() as session:
        stored = (await session.execute(select(Turn))).scalars().all()
        assert len(stored) == 1
        row = stored[0]
        assert row.child_text == "Zasto je nebo plavo?"
        assert row.bruno_text and "Nebo je plavo!" in row.bruno_text
        assert row.language == "sr"
        assert row.router_decision == "llm"
        assert row.profile == "server"
        assert row.delete_after > row.created_at
        assert row.prompt_version and row.prompt_version.startswith("system_v1_sr.txt@")

        metrics = (await session.execute(select(TurnMetrics))).scalars().all()
        assert len(metrics) == 1
        measured = metrics[0]
        assert measured.stt_ms == 120
        # mocked synthesis is instant, so this can legitimately be 0 ms
        assert measured.first_audio_ms is not None
        assert measured.total_ms is not None
        assert measured.prompt_tokens_cached == 280
        assert measured.output_tokens == 12
        assert measured.error_code is None

        sessions = (await session.execute(select(Session))).scalars().all()
        assert len(sessions) == 1
        assert sessions[0].ended_at is not None, "the sitting must be closed on disconnect"


async def test_the_second_turn_of_a_session_can_see_the_first(
    client: AsyncClient,
    parent_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """History comes from this session's stored turns (DATA_MODEL.md §3.1)."""
    token = await _child_session(client, parent_headers)
    await _drive(
        [
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.2},
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.2},
        ],
        token,
    )
    async with session_factory() as session:
        rows = (await session.execute(select(Turn).order_by(Turn.created_at))).scalars().all()
        assert len(rows) == 2
        # both belong to one sitting
        assert rows[0].session_id == rows[1].session_id


# --- the things that go wrong (UC-22, NFR-09) --------------------------------------


async def test_a_tap_instead_of_a_hold_asks_the_child_to_hold_the_paw(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    token = await _child_session(client, parent_headers)
    short = b"\x00\x01" * int(turn.SAMPLE_RATE * 0.1)  # 100 ms
    socket = await _drive(
        [
            _message(type="turn.start"),
            _frame(1, short),
            _message(type="turn.end"),
            {"sleep": 0.1},
        ],
        token,
    )
    assert socket.codes() == ["hold_paw"]
    assert socket.binary == [], "nothing should be synthesized for a tap"


async def test_silence_is_answered_with_the_not_heard_line(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    token = await _child_session(client, parent_headers)
    socket = await _drive(
        [
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.2},
        ],
        token,
        _inference(transcript="", no_speech=0.95),
    )
    assert socket.codes() == ["stt_empty"]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"stt_status": 500}, "stt_failed"),
        ({"llm_status": 503}, "llm_failed"),
        ({"tts_status": 503}, "tts_failed"),
    ],
)
async def test_every_pipeline_failure_ends_in_a_code_and_never_in_text(
    client: AsyncClient,
    parent_headers: dict[str, str],
    kwargs: dict[str, Any],
    expected: str,
) -> None:
    token = await _child_session(client, parent_headers)
    socket = await _drive(
        [
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.3},
        ],
        token,
        _inference(**kwargs),
    )
    assert socket.codes() == [expected]
    assert socket.states()[-1] == turn.STATE_IDLE, "the character must settle back"
    # every error payload carries a code and nothing else
    for event in socket.events("error"):
        assert set(event) == {"type", "code"}


async def test_a_failed_turn_is_still_recorded_with_its_error_code(
    client: AsyncClient,
    parent_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A turn that failed is the one worth looking at (EVALUATION.md §4.1)."""
    token = await _child_session(client, parent_headers)
    await _drive(
        [
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.3},
        ],
        token,
        _inference(llm_status=503),
    )
    async with session_factory() as session:
        metrics = (await session.execute(select(TurnMetrics))).scalars().all()
        assert len(metrics) == 1
        assert metrics[0].error_code == "llm_failed"
        turns = (await session.execute(select(Turn))).scalars().all()
        assert turns[0].child_text is None, "a failed turn stores no text"


# --- barge-in and the caps ---------------------------------------------------------


async def test_pressing_the_paw_again_abandons_the_answer_in_flight(
    client: AsyncClient,
    parent_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Barge-in (§6.1): the running turn is cancelled, not left to finish."""
    token = await _child_session(client, parent_headers)
    socket = await _drive(
        [
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.3},
        ],
        token,
    )
    assert socket.events("turn.done"), "the second turn should still complete"
    async with session_factory() as session:
        rows = (await session.execute(select(Turn).order_by(Turn.created_at))).scalars().all()
        interrupted = [row for row in rows if row.interrupted]
        assert interrupted, "the abandoned turn should be recorded as interrupted"


async def test_turn_cancel_settles_the_character_and_drops_the_audio(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    token = await _child_session(client, parent_headers)
    socket = await _drive(
        [
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.cancel"),
            {"sleep": 0.1},
        ],
        token,
    )
    assert socket.states()[-1] == turn.STATE_IDLE
    assert socket.binary == []
    assert socket.codes() == []


async def test_audio_beyond_the_fifteen_second_cap_is_dropped(
    client: AsyncClient, parent_headers: dict[str, str]
) -> None:
    token = await _child_session(client, parent_headers)
    one_second = ONE_SECOND
    script: list[dict[str, Any]] = [_message(type="turn.start")]
    script += [_frame(i, one_second) for i in range(1, 21)]  # 20 seconds
    script += [_message(type="turn.end"), {"sleep": 0.2}]
    socket = await _drive(script, token, _inference())
    # the turn still runs: the child is not punished for talking too long
    assert socket.events("turn.done")
    assert turn.MAX_AUDIO_BYTES == 15_000 * turn.SAMPLE_RATE * 2 // 1000


async def test_frames_outside_a_turn_are_ignored(client: AsyncClient, parent_headers: dict[str, str]) -> None:
    """A frame with no turn.start before it must not start one by accident."""
    token = await _child_session(client, parent_headers)
    socket = await _drive([_frame(1, ONE_SECOND), _message(type="turn.end"), {"sleep": 0.1}], token)
    assert socket.binary == []
    assert socket.codes() == []
    assert socket.events("turn.done") == []


async def test_turns_are_rate_limited_per_child(
    client: AsyncClient, parent_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ARCHITECTURE.md §9: turns 20/min per child."""
    from app.config import settings

    monkeypatch.setattr(settings, "turn_rate_limit_per_minute", 1)
    token = await _child_session(client, parent_headers)
    socket = await _drive(
        [
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.2},
            _message(type="turn.start"),
            _frame(1, ONE_SECOND),
            _message(type="turn.end"),
            {"sleep": 0.1},
        ],
        token,
    )
    assert "rate_limited" in socket.codes()


# --- the queue ---------------------------------------------------------------------


async def test_a_child_who_waits_too_long_for_a_slot_hears_the_fallback() -> None:
    """§6.3: beyond the parallel slots, requests queue for at most 10 s."""
    full = turn.Slots(count=0, max_wait_s=0.05)
    with pytest.raises(turn.QueueFullError):
        async with full:
            pass  # pragma: no cover - acquiring an empty semaphore cannot succeed


async def test_the_queue_reports_how_long_the_wait_was() -> None:
    free = turn.Slots(count=1, max_wait_s=1.0)
    async with free as waited_ms:
        assert waited_ms < 50

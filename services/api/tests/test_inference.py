"""The inference layer: registry resolution and the three clients.

No service is started here. Each client is given an httpx MockTransport, so these tests
describe the contract the llm, stt and tts containers have to keep - and they fail if
someone changes the shape the pipeline depends on.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import settings
from app.inference import Inference, InferenceError, Message
from app.inference import registry as model_registry
from app.inference.clients import LanguageModelClient, SpeechToText, TextToSpeech


@pytest.fixture(autouse=True)
def _fresh_registry() -> Iterator[None]:
    model_registry.reload()
    yield
    model_registry.reload()


def _transport(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- the registry ------------------------------------------------------------------


def test_the_default_model_is_resolved_with_its_endpoint() -> None:
    model = model_registry.language_model()
    assert model.id
    # ${LLM_SERVER_URL} must be gone: an unexpanded placeholder would be requested as a
    # literal hostname and fail at the socket, far from the cause
    assert "${" not in model.endpoint
    assert model.endpoint.startswith(settings.llm_server_url.rstrip("/"))


def test_a_model_the_environment_does_not_activate_is_refused() -> None:
    """A benchmark-only model must not be servable to a child by accident (F-20)."""
    document = model_registry.document()
    eval_only = [
        item["id"]
        for item in document["models"]
        if settings.environment not in (item.get("active_envs") or [])
    ]
    assert eval_only, "the registry no longer has a model outside this environment"
    with pytest.raises(model_registry.RegistryError, match="not active"):
        model_registry.language_model(model_id=eval_only[0])


def test_an_unknown_model_names_what_the_registry_has() -> None:
    with pytest.raises(model_registry.RegistryError, match="no model"):
        model_registry.language_model(model_id="no-such-model")


def test_a_broken_registry_path_is_reported_once(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "model_registry_path", str(tmp_path / "missing.yaml"))
    model_registry.reload()
    with pytest.raises(model_registry.RegistryError, match="cannot read"):
        model_registry.language_model()


def test_every_voice_has_a_language_and_the_internal_one_is_marked() -> None:
    found = model_registry.voices()
    assert {"sr", "en"} <= set(found)
    # the Serbian voice is non-commercial; the flag is what keeps it off a public URL
    assert found["sr"].internal_only is True
    assert found["en"].internal_only is False


# --- speech to text ----------------------------------------------------------------


async def test_transcribe_sends_raw_audio_and_the_forced_language() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "text": "zdravo",
                "confidence": 0.8,
                "no_speech_prob": 0.01,
                "duration_ms": 1200,
                "stt_ms": 300,
                "model_id": "stt-under-test",
            },
        )

    async with _transport(handler) as client:
        result = await SpeechToText(client).transcribe(b"\x01\x02" * 100, language="sr")

    assert seen["body"] == b"\x01\x02" * 100, "audio must be sent as-is, not re-encoded"
    assert "language=sr" in seen["url"], "the child's language is never guessed (§6.2)"
    assert result.text == "zdravo"
    assert result.confidence == 0.8


async def test_empty_audio_never_reaches_the_service() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("a press too short to hold any audio must not be sent")

    async with _transport(handler) as client:
        with pytest.raises(InferenceError, match="no audio"):
            await SpeechToText(client).transcribe(b"", language="en")


async def test_a_failing_stt_service_raises_one_kind_of_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with _transport(handler) as client:
        with pytest.raises(InferenceError) as caught:
            await SpeechToText(client).transcribe(b"\x00\x00", language="en")
    assert caught.value.service == "stt"


# --- text to speech ----------------------------------------------------------------


async def test_synthesize_returns_the_wav_and_its_measurements() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"text": "Zdravo!", "language": "sr"}
        return httpx.Response(
            200,
            content=b"RIFF....WAVE",
            headers={"X-Sample-Rate": "22050", "X-Audio-Ms": "900", "X-Synth-Ms": "40"},
        )

    async with _transport(handler) as client:
        speech = await TextToSpeech(client).synthesize("Zdravo!", language="sr")

    assert speech.wav == b"RIFF....WAVE"
    assert (speech.sample_rate, speech.audio_ms, speech.synth_ms) == (22050, 900, 40)


async def test_a_language_without_a_voice_is_an_inference_error_not_a_crash() -> None:
    """503 is how tts reports "this language has no usable voice" (§6.4)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="internal_only")

    async with _transport(handler) as client:
        with pytest.raises(InferenceError) as caught:
            await TextToSpeech(client).synthesize("Zdravo!", language="sr")
    assert caught.value.service == "tts"
    assert caught.value.detail == "503"


# --- the language model ------------------------------------------------------------


def _sse(*chunks: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def _delta(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}, "finish_reason": None}]}


async def test_generation_streams_pieces_and_then_reports_what_it_cost() -> None:
    body = _sse(
        _delta("Nebo "),
        _delta("je plavo."),
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 96},
            },
            "timings": {"prompt_per_second": 500.0, "predicted_per_second": 130.0},
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        assert sent["stream"] is True
        assert sent["stream_options"] == {"include_usage": True}
        # §6.3: thinking stays off, and the switch comes from the registry
        assert sent["chat_template_kwargs"]["enable_thinking"] is False
        return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})

    async with _transport(handler) as client:
        llm = LanguageModelClient(client)
        async with llm.generate([Message("user", "Zasto je nebo plavo?")]) as stream:
            pieces = [piece async for piece in stream]

    assert "".join(pieces) == "Nebo je plavo."
    assert stream.usage.prompt_tokens == 120
    assert stream.usage.prompt_tokens_cached == 96
    assert stream.usage.output_tokens == 7
    assert stream.usage.decode_tps == 130.0
    # measured, not reported: the first piece is what the child waits for
    assert stream.usage.ttft_ms is not None
    assert stream.usage.truncated is False


async def test_hitting_max_tokens_is_recorded_as_truncated() -> None:
    body = _sse(_delta("Prica koja nikada"), {"choices": [{"delta": {}, "finish_reason": "length"}]})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})

    async with (
        _transport(handler) as client,
        LanguageModelClient(client).generate([Message("user", "prica")]) as stream,
    ):
        [piece async for piece in stream]
    assert stream.usage.truncated is True


async def test_a_chunk_that_is_not_json_is_skipped_rather_than_fatal() -> None:
    body = b"data: {not json}\n\n" + _sse(_delta("ok"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})

    async with (
        _transport(handler) as client,
        LanguageModelClient(client).generate([Message("user", "x")]) as stream,
    ):
        pieces = [piece async for piece in stream]
    assert "".join(pieces) == "ok"


async def test_an_llm_that_refuses_the_request_raises_before_any_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="no slot")

    async with _transport(handler) as client:
        with pytest.raises(InferenceError) as caught:
            async with LanguageModelClient(client).generate([Message("user", "x")]):
                pass
    assert caught.value.service == "llm"


async def test_the_bundle_shares_one_connection_pool_and_closes_it() -> None:
    bundle = Inference.create()
    assert bundle.stt._client is bundle.client
    assert bundle.tts._client is bundle.client
    assert bundle.llm.client is bundle.client
    await bundle.aclose()
    assert bundle.client.is_closed

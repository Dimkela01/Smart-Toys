"""Clients for the three inference services (ARCHITECTURE.md §6.2-6.4).

One interface per service, so the server and device profiles differ only in the endpoint
the registry resolves, and so a different runtime can be substituted without touching the
turn pipeline. The classes here do transport and measurement only: splitting sentences,
stripping thinking and deciding what to say belong to the orchestrator.

docs/CLAUDE.md §2 applies throughout: audio is passed as bytes and never written
anywhere, and no transcript or answer text is logged - the log lines carry sizes,
durations and ids.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Self

import httpx

from app.config import Language, Profile, settings
from app.inference import registry

logger = logging.getLogger("app.inference")

Role = Literal["system", "user", "assistant"]

#: NFR-01's budget is first audio, not the whole answer, so the per-service ceilings are
#: generous: the orchestrator gives up on its own schedule and plays a fallback line.
STT_TIMEOUT_S = 20.0
TTS_TIMEOUT_S = 20.0
LLM_CONNECT_TIMEOUT_S = 5.0
#: a slot may be busy with another child; §6.3 allows a 10 s wait before the fallback
LLM_READ_TIMEOUT_S = 30.0


class InferenceError(RuntimeError):
    """A service was unreachable or answered with something unusable."""

    def __init__(self, service: str, detail: str) -> None:
        super().__init__(f"{service}: {detail}")
        self.service = service
        self.detail = detail


@dataclass(frozen=True)
class Transcript:
    """What the child said (§6.2). `text` is never logged."""

    text: str
    confidence: float
    no_speech_prob: float
    duration_ms: int
    stt_ms: int
    model_id: str


@dataclass(frozen=True)
class Speech:
    """One sentence as audio (§6.4)."""

    wav: bytes
    sample_rate: int
    audio_ms: int
    synth_ms: int


@dataclass
class Message:
    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class Usage:
    """What a generation cost, for turn_metrics (EVALUATION.md §4.1)."""

    model_id: str = ""
    prompt_tokens: int = 0
    prompt_tokens_cached: int = 0
    output_tokens: int = 0
    ttft_ms: int | None = None
    llm_total_ms: int = 0
    prefill_tps: float | None = None
    decode_tps: float | None = None
    truncated: bool = False


class SpeechToText:
    """The speech-to-text service behind HTTP (§6.2)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def transcribe(self, audio: bytes, *, language: Language) -> Transcript:
        """`audio` is 16 kHz mono PCM16, as the browser worklet sends it (§6.1)."""
        if not audio:
            raise InferenceError("stt", "no audio")
        url = f"{settings.stt_server_url.rstrip('/')}/transcribe"
        try:
            response = await self._client.post(
                url,
                params={"language": language},
                content=audio,
                headers={"Content-Type": "application/octet-stream"},
                timeout=STT_TIMEOUT_S,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as error:
            raise InferenceError("stt", str(error)) from error
        return Transcript(
            text=str(body.get("text", "")),
            confidence=float(body.get("confidence", 0.0)),
            no_speech_prob=float(body.get("no_speech_prob", 1.0)),
            duration_ms=int(body.get("duration_ms", 0)),
            stt_ms=int(body.get("stt_ms", 0)),
            model_id=str(body.get("model_id", "")),
        )


class TextToSpeech:
    """The text-to-speech service behind HTTP, one voice per language (§6.4)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def synthesize(self, text: str, *, language: Language) -> Speech:
        url = f"{settings.tts_server_url.rstrip('/')}/synthesize"
        try:
            response = await self._client.post(
                url,
                json={"text": text, "language": language},
                timeout=TTS_TIMEOUT_S,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            # 503 means this language has no usable voice, which is a configuration fact
            # rather than a failure of this turn; the caller plays its fallback audio
            raise InferenceError("tts", f"{error.response.status_code}") from error
        except httpx.HTTPError as error:
            raise InferenceError("tts", str(error)) from error
        headers = response.headers
        return Speech(
            wav=response.content,
            sample_rate=int(headers.get("X-Sample-Rate", 0)),
            audio_ms=int(headers.get("X-Audio-Ms", 0)),
            synth_ms=int(headers.get("X-Synth-Ms", 0)),
        )


class Generation:
    """A streaming completion. Iterate for text, then read `usage`.

        async with llm.generate(messages) as stream:
            async for piece in stream:
                ...
        stream.usage.ttft_ms

    The pieces are raw model output: the orchestrator strips thinking and splits
    sentences, because both have to survive a tag arriving in two pieces.
    """

    def __init__(self, client: httpx.AsyncClient, request: dict[str, Any], url: str, model_id: str):
        self._client = client
        self._request = request
        self._url = url
        self._stream: Any = None
        self._response: httpx.Response | None = None
        self.usage = Usage(model_id=model_id)

    async def __aenter__(self) -> Self:
        self._started = time.perf_counter()
        self._stream = self._client.stream(
            "POST",
            self._url,
            json=self._request,
            timeout=httpx.Timeout(LLM_READ_TIMEOUT_S, connect=LLM_CONNECT_TIMEOUT_S),
        )
        try:
            self._response = await self._stream.__aenter__()
            self._response.raise_for_status()
        except httpx.HTTPError as error:
            await self._stream.__aexit__(type(error), error, error.__traceback__)
            raise InferenceError("llm", str(error)) from error
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._stream is not None:
            await self._stream.__aexit__(*exc)

    async def __aiter__(self) -> AsyncIterator[str]:
        assert self._response is not None, "use `async with` before iterating"
        first = True
        async for line in self._response.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload in {"", "[DONE]"}:
                continue
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                logger.warning("llm sent a chunk that is not JSON (%d bytes)", len(payload))
                continue
            self._absorb_usage(chunk)
            for choice in chunk.get("choices") or []:
                if choice.get("finish_reason") == "length":
                    self.usage.truncated = True
                piece = (choice.get("delta") or {}).get("content")
                if not piece:
                    continue
                if first:
                    self.usage.ttft_ms = int(1000 * (time.perf_counter() - self._started))
                    first = False
                yield piece
        self.usage.llm_total_ms = int(1000 * (time.perf_counter() - self._started))

    def _absorb_usage(self, chunk: dict[str, Any]) -> None:
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            self.usage.prompt_tokens = int(usage.get("prompt_tokens") or 0)
            self.usage.output_tokens = int(usage.get("completion_tokens") or 0)
            details = usage.get("prompt_tokens_details") or {}
            self.usage.prompt_tokens_cached = int(details.get("cached_tokens") or 0)
        timings = chunk.get("timings")
        if isinstance(timings, dict):
            self.usage.prefill_tps = _as_float(timings.get("prompt_per_second"))
            self.usage.decode_tps = _as_float(timings.get("predicted_per_second"))


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


@dataclass
class LanguageModelClient:
    """An OpenAI-compatible chat endpoint (§6.3)."""

    client: httpx.AsyncClient
    profile: Profile | None = None
    _model: registry.LanguageModel | None = field(default=None, repr=False)

    @property
    def model(self) -> registry.LanguageModel:
        if self._model is None:
            self._model = registry.language_model(profile=self.profile)
        return self._model

    def generate(
        self,
        messages: Sequence[Message],
        *,
        max_tokens: int = 150,
        temperature: float = 0.7,
    ) -> Generation:
        model = self.model
        request: dict[str, Any] = {
            "model": model.id,
            "messages": [message.as_dict() for message in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            # llama.cpp only reports usage and timings in the final chunk if asked
            "stream_options": {"include_usage": True},
            "timings_per_token": True,
        }
        if model.options:
            # §6.3: the family's own switches, e.g. keeping thinking off
            request["chat_template_kwargs"] = dict(model.options)
        return Generation(self.client, request, f"{model.endpoint}/chat/completions", model.id)


@dataclass
class Inference:
    """The three clients, sharing one connection pool."""

    client: httpx.AsyncClient
    stt: SpeechToText
    tts: TextToSpeech
    llm: LanguageModelClient

    @classmethod
    def create(cls, *, profile: Profile | None = None) -> Inference:
        client = httpx.AsyncClient(timeout=httpx.Timeout(STT_TIMEOUT_S))
        return cls(
            client=client,
            stt=SpeechToText(client),
            tts=TextToSpeech(client),
            llm=LanguageModelClient(client, profile=profile),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

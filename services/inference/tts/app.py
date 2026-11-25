"""Text-to-speech service (ARCHITECTURE.md §6.4).

Interface (§6.4):  synthesize(text, language, voice_id) -> PCM16 WAV

Two engines behind one interface, chosen by the registry entry's `runtime`:

* **kokoro** - Kokoro-82M, apache-2.0, English. The voice we can ship.
* **piper**  - a Piper-class VITS voice, used for Serbian. The only `sr` voice that
  exists is a placeholder: its dataset is CC BY-NC-SA 4.0 and a native speaker judged
  the pronunciation bad, so it is marked `internal_only` in the registry and a recorded
  voice will replace it. See models/registry.yaml and docs/reports/M2.md.

`internal_only` voices are refused unless TTS_ALLOW_INTERNAL_ONLY is set, so a
deployment that forgets the flag loses the Serbian voice rather than publishing an
unlicensed one (docs/CLAUDE.md §3).

Nothing is written to disk and no synthesized text is logged: the log lines carry a
request id and a character count only (docs/CLAUDE.md §2).
"""

from __future__ import annotations

import io
import logging
import os
import re
import sys
import time
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal, Protocol
from uuid import uuid4

from fastapi import FastAPI, Response
from pydantic import BaseModel, Field

sys.path.insert(0, "/srv/inference")

from common import registry

LOG = logging.getLogger("tts")

Language = Literal["sr", "en"]

#: markdown the LLM may emit despite the prompt; the child hears words, not asterisks
_MARKDOWN = re.compile(r"[*_`#>\[\]()]+")
#: emoji and other symbols a voice cannot pronounce
_SYMBOLS = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0000fe00-\U0000fe0f\U0001f1e6-\U0001f1ff]+"
)
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """§6.4: strip markdown and emoji before synthesis.

    Digits are left alone on purpose: both engines read numbers out themselves, and
    Serbian numerals are inflected, so a naive digit-to-word pass would be wrong more
    often than the engine is.
    """
    return _SPACES.sub(" ", _SYMBOLS.sub(" ", _MARKDOWN.sub(" ", text))).strip()


class Engine(Protocol):
    sample_rate: int
    voice_id: str

    def speak(self, text: str) -> bytes:
        """Return PCM16 little-endian mono samples (no WAV header)."""


class KokoroEngine:
    """Kokoro-82M through its own package; English only (§6.4)."""

    def __init__(self, entry: dict[str, Any]) -> None:
        import torch
        from kokoro import KModel, KPipeline

        self.voice_id = str(entry["id"])
        directory = registry.weights_dir("tts", self.voice_id)
        self.sample_rate = 24_000
        model = KModel(
            config=str(directory / "config.json"),
            model=str(directory / "kokoro-v1_0.pth"),
        ).eval()
        # "a" is Kokoro's American English pipeline
        self._pipeline = KPipeline(lang_code="a", model=model)
        name = os.environ.get("TTS_EN_VOICE", "af_heart")
        self._voice = torch.load(str(directory / "voices" / f"{name}.pt"), weights_only=True)
        self._torch = torch

    def speak(self, text: str) -> bytes:
        parts = [chunk.audio for chunk in self._pipeline(text, voice=self._voice)]
        if not parts:
            return b""
        audio = self._torch.cat(parts).clamp(-1.0, 1.0)
        return (audio * 32767.0).to(self._torch.int16).numpy().tobytes()


class PiperEngine:
    """A Piper-class VITS voice through the piper package.

    piper is GPL-3.0-or-later. It runs here as a separate service that is not
    distributed, so the licence is a deployment question rather than a code one; it is
    recorded in docs/reports/M2.md because a shipped device profile would have to
    answer it. The English path does not use piper.
    """

    def __init__(self, entry: dict[str, Any]) -> None:
        from piper import PiperVoice

        self.voice_id = str(entry["id"])
        directory = registry.weights_dir("tts", self.voice_id)
        model = next(directory.rglob("*.onnx"), None)
        if model is None:
            raise SystemExit(f"no .onnx voice under {directory}; run `make models`")
        self._voice = PiperVoice.load(str(model), config_path=f"{model}.json")
        self.sample_rate = int(self._voice.config.sample_rate)

    def speak(self, text: str) -> bytes:
        return b"".join(chunk.audio_int16_bytes for chunk in self._voice.synthesize(text))


_engines: dict[str, Engine] = {}
_refused: dict[str, str] = {}

ENGINES = {"kokoro": KokoroEngine, "piper": PiperEngine}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    allow_internal = os.environ.get("TTS_ALLOW_INTERNAL_ONLY", "").lower() in {"1", "true", "yes"}
    for entry in registry.registry().get("tts") or []:
        language = str(entry.get("language"))
        voice_id = str(entry.get("id"))
        if entry.get("internal_only") and not allow_internal:
            _refused[language] = f"{voice_id} is internal_only and TTS_ALLOW_INTERNAL_ONLY is not set"
            LOG.warning("refusing %s: %s", language, _refused[language])
            continue
        runtime = str(entry.get("runtime"))
        if runtime not in ENGINES:
            _refused[language] = f"no engine for runtime {runtime!r}"
            LOG.warning("refusing %s: %s", language, _refused[language])
            continue
        started = time.perf_counter()
        _engines[language] = ENGINES[runtime](entry)
        LOG.info(
            "loaded %s voice %s (%s) in %.1f s",
            language,
            voice_id,
            runtime,
            time.perf_counter() - started,
        )
    if not _engines:
        raise SystemExit("no usable TTS voice; see the warnings above")
    yield
    _engines.clear()


app = FastAPI(title="bruno-tts", lifespan=lifespan, docs_url=None, redoc_url=None)


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    language: Language
    #: reserved for per-character voices (CONTENT.md); one voice per language in M2
    voice_id: str | None = None


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok" if _engines else "loading",
        "voices": {lang: engine.voice_id for lang, engine in _engines.items()},
        "unavailable": _refused,
    }


@app.post("/synthesize")
async def synthesize(payload: SynthesizeRequest) -> Response:
    engine = _engines.get(payload.language)
    if engine is None:
        reason = _refused.get(payload.language, "no voice for this language")
        LOG.warning("no voice for %s: %s", payload.language, reason)
        # the orchestrator plays its local fallback audio; the child never sees text
        return Response(status_code=503, content=reason.encode(), media_type="text/plain")

    request_id = uuid4().hex[:12]
    text = normalize(payload.text)
    if not text:
        return Response(status_code=422, content=b"nothing to say", media_type="text/plain")

    started = time.perf_counter()
    pcm = engine.speak(text)
    elapsed_ms = int(1000 * (time.perf_counter() - started))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(engine.sample_rate)
        handle.writeframes(pcm)
    audio_ms = int(1000 * len(pcm) / 2 / engine.sample_rate)

    LOG.info(
        "tts %s: %s, %d chars -> %d ms audio in %d ms",
        request_id,
        payload.language,
        len(text),
        audio_ms,
        elapsed_ms,
    )
    return Response(
        content=buffer.getvalue(),
        media_type="audio/wav",
        headers={
            "X-Audio-Ms": str(audio_ms),
            "X-Synth-Ms": str(elapsed_ms),
            "X-Sample-Rate": str(engine.sample_rate),
        },
    )

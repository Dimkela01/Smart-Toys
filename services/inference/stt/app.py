"""Speech-to-text service: faster-whisper base, int8, CPU (ARCHITECTURE.md §6.2).

Interface (§6.2):  transcribe(audio_pcm16, language) -> {text, confidence,
no_speech_prob, duration_ms}

Two rules from docs/CLAUDE.md §2 shape this file:

* **Audio is never stored.** The request body is decoded into a numpy array, transcribed
  and dropped. Nothing is written to disk, and the body is not kept after the response.
* **Transcript text is never logged.** The log lines below carry a request id, the audio
  duration and the number of characters - never the words themselves.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from math import exp
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from fastapi import FastAPI, Query, Request, Response
from faster_whisper import WhisperModel

# common/ is copied in beside this file by the Dockerfile
sys.path.insert(0, "/srv/inference")

from common import registry

LOG = logging.getLogger("stt")

#: the child's language is always known, so Whisper never has to guess (§6.2)
Language = Literal["sr", "en"]

#: 16 kHz mono PCM16, as the browser worklet sends it (§6.1)
SAMPLE_RATE = 16_000

_model: WhisperModel | None = None
_model_id = ""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _model, _model_id
    entry = registry.entry("stt", os.environ.get("STT_MODEL_ID") or None)
    _model_id = str(entry["id"])
    directory = registry.weights_dir("stt", _model_id)
    if not (directory / "model.bin").exists():
        raise SystemExit(f"missing weights for {_model_id}: {directory}\nRun `make models`.")
    threads = int(os.environ.get("STT_THREADS") or os.cpu_count() or 4)
    LOG.info("loading %s (%s) with %d threads", _model_id, entry["compute_type"], threads)
    _model = WhisperModel(
        str(directory),
        device="cpu",
        compute_type=str(entry["compute_type"]),
        cpu_threads=threads,
    )
    LOG.info("ready")
    yield
    _model = None


app = FastAPI(title="bruno-stt", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok" if _model is not None else "loading", "model": _model_id}


@app.post("/transcribe")
async def transcribe(
    request: Request,
    language: Language = Query(..., description="the child's language; never guessed"),
) -> dict[str, Any]:
    """Transcribe raw 16 kHz mono PCM16 sent as the request body."""
    assert _model is not None, "called before the model finished loading"
    request_id = uuid4().hex[:12]
    raw = await request.body()

    # PCM16 -> float32 in [-1, 1); an odd trailing byte would be half a sample
    samples = np.frombuffer(raw[: len(raw) - len(raw) % 2], dtype="<i2")
    audio = samples.astype(np.float32) / 32768.0
    duration_ms = int(1000 * len(audio) / SAMPLE_RATE)

    started = time.perf_counter()
    segments, info = _model.transcribe(
        audio,
        language=language,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    # the generator is lazy: this is where the work happens
    parts = list(segments)
    elapsed_ms = int(1000 * (time.perf_counter() - started))

    text = " ".join(part.text.strip() for part in parts).strip()
    # avg_logprob is a mean log probability per token; exp() puts it back on 0..1 so the
    # orchestrator can compare it with one threshold (SAFETY.md asks for a low-confidence
    # path). With no speech at all there is no segment, so confidence is 0.
    confidence = exp(sum(p.avg_logprob for p in parts) / len(parts)) if parts else 0.0
    no_speech = max((p.no_speech_prob for p in parts), default=1.0)

    LOG.info(
        "stt %s: %d ms audio, %d ms work, %d chars, confidence %.2f",
        request_id,
        duration_ms,
        elapsed_ms,
        len(text),
        confidence,
    )
    return {
        "text": text,
        "confidence": round(confidence, 4),
        "no_speech_prob": round(float(no_speech), 4),
        "duration_ms": duration_ms,
        "stt_ms": elapsed_ms,
        "model_id": _model_id,
        "language": info.language,
    }


@app.get("/")
async def root() -> Response:
    return Response(status_code=204)

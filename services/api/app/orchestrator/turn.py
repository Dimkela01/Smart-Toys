"""One turn, from the child's audio to ordered sentences of speech (ARCHITECTURE.md §6).

The pipeline yields events as it goes rather than returning a result, because the point
of it is that the first sentence reaches the child while the model is still writing the
second (NFR-02: end of speech to first audio, p50 <= 4 s).

Two rules shape the error handling:

* **NFR-09:** any failure ends in a spoken fallback line, never a technical message on
  the child's screen. So every failure here becomes a `Failed` event carrying a code; the
  client maps the code to one of its bundled audio files and says nothing.
* **docs/CLAUDE.md §2:** audio stays in memory, and no transcript or answer text is
  logged. `Finished` carries the texts for the database, which is not a log.

Safety layers L1 (router) and L4 (output filter) belong between STT and the prompt, and
between a sentence and its synthesis. They arrive with M3; the seams are marked below.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.config import Language, Profile, settings
from app.inference import Inference, InferenceError, Speech, Transcript, Usage
from app.orchestrator import prompt
from app.orchestrator.text import SentenceStream, ThinkFilter

logger = logging.getLogger("app.orchestrator.turn")

#: character states the client animates (UI.md §3.3). `listening` is driven by the client
#: while the paw is held; the rest are server-driven.
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"
STATE_IDLE = "idle"

#: 16 kHz mono PCM16 (§6.1)
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2

#: a press this short carries no speech; the child is told to hold the paw instead
MIN_AUDIO_MS = 400
#: the cap on one press (§6.1); the client stops sending at the same point
MAX_AUDIO_MS = 15_000
MAX_AUDIO_BYTES = MAX_AUDIO_MS * SAMPLE_RATE * BYTES_PER_SAMPLE // 1000

#: above this, the speech-to-text service decided the audio held no speech
NO_SPEECH_LIMIT = 0.6


@dataclass(frozen=True)
class Thinking:
    """The toy is working; the client shows the state and plays its instant sound."""

    state: str = STATE_THINKING


@dataclass(frozen=True)
class Speaking:
    """One sentence as audio, in order. `seq` starts at 1."""

    seq: int
    wav: bytes
    sample_rate: int


@dataclass
class Metrics:
    """Mirrors turn_metrics (EVALUATION.md §4.1). Every field may stay None."""

    stt_ms: int | None = None
    stt_confidence: float | None = None
    prompt_tokens: int | None = None
    prompt_tokens_cached: int | None = None
    output_tokens: int | None = None
    ttft_ms: int | None = None
    prefill_tps: float | None = None
    decode_tps: float | None = None
    llm_total_ms: int | None = None
    tts_first_ms: int | None = None
    first_audio_ms: int | None = None
    total_ms: int | None = None
    truncated: bool = False
    error_code: str | None = None
    #: not in turn_metrics; used to decide whether the queue made the child wait
    queue_ms: int | None = None


@dataclass
class Finished:
    """The turn is done. The texts are for the database, never for the child client."""

    child_text: str
    answer_text: str
    sentences: int
    metrics: Metrics
    model_id: str
    prompt_version: str


@dataclass
class Failed:
    """A code the client turns into one of its own audio files (NFR-09, UC-22)."""

    code: str
    metrics: Metrics


Event = Thinking | Speaking | Finished | Failed


@dataclass(frozen=True)
class TurnContext:
    """Everything one turn needs to know, gathered before any audio arrives."""

    child: prompt.Child
    character: prompt.Character
    history: list[prompt.Turn] = field(default_factory=list)
    profile: Profile = "server"

    @property
    def language(self) -> Language:
        return self.child.language


class Slots:
    """The LLM's parallel slots, as a queue with a maximum wait (§6.3, NFR-12).

    llama-server would accept every request and make them all slow together. Waiting
    here instead means a third child gets a short "thinking" line and then an answer,
    rather than everyone getting a late one.
    """

    def __init__(self, count: int, max_wait_s: float) -> None:
        self._semaphore = asyncio.Semaphore(count)
        self._max_wait_s = max_wait_s

    async def __aenter__(self) -> float:
        started = time.perf_counter()
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self._max_wait_s)
        except TimeoutError as error:
            raise QueueFullError() from error
        return (time.perf_counter() - started) * 1000

    async def __aexit__(self, *exc: object) -> None:
        self._semaphore.release()


class QueueFullError(RuntimeError):
    """Every slot was busy for longer than a child will wait."""


_slots: Slots | None = None


def slots() -> Slots:
    global _slots
    if _slots is None:
        _slots = Slots(settings.llm_parallel, settings.llm_queue_max_wait_seconds)
    return _slots


def audio_ms(audio: bytes) -> int:
    return int(1000 * len(audio) / BYTES_PER_SAMPLE / SAMPLE_RATE)


async def run(
    inference: Inference,
    context: TurnContext,
    audio: bytes,
) -> AsyncIterator[Event]:
    """Run one turn. Cancelling the iteration stops the work (barge-in, §6.1)."""
    started = time.perf_counter()
    metrics = Metrics()
    language = context.language

    held_ms = audio_ms(audio)
    if held_ms < MIN_AUDIO_MS:
        # not an error: the child tapped instead of holding (UC-22)
        metrics.error_code = "hold_paw"
        yield Failed("hold_paw", metrics)
        return

    yield Thinking()

    transcript = await _transcribe(inference, audio, language, metrics)
    if isinstance(transcript, Failed):
        yield transcript
        return

    # L1 router goes here in M3: protected categories and parent-blocked topics are
    # answered from prompts/fixed_responses before the model is ever asked.

    built = prompt.build(
        child=context.child,
        character=context.character,
        child_message=transcript.text,
        history=context.history,
    )
    metrics.prompt_tokens = built.estimated_tokens

    answer: list[str] = []
    model_id = ""
    try:
        async with slots() as waited_ms:
            metrics.queue_ms = int(waited_ms)
            generation = inference.llm.generate(built.messages, max_tokens=prompt.MAX_ANSWER_TOKENS)
            async with generation as stream:
                model_id = stream.usage.model_id
                think = ThinkFilter()
                splitter = SentenceStream()

                async def complete_sentences() -> AsyncIterator[str]:
                    """Sentences as they finish, then whatever the tail leaves over."""
                    async for piece in stream:
                        for sentence in splitter.feed(think.feed(piece)):
                            yield sentence
                    for sentence in splitter.feed(think.close()):
                        yield sentence
                    for sentence in splitter.close():
                        yield sentence

                async for sentence in complete_sentences():
                    # L4 output filter goes here in M3: a sentence that fails is not
                    # spoken, and the turn ends with the safe fallback line.
                    spoken = await _speak(inference, sentence, language, metrics, started)
                    if spoken is None:
                        metrics.error_code = "tts_failed"
                        yield Failed("tts_failed", metrics)
                        return
                    answer.append(sentence)
                    yield Speaking(seq=len(answer), wav=spoken.wav, sample_rate=spoken.sample_rate)
            _absorb(metrics, stream.usage)
    except QueueFullError:
        logger.warning("every llm slot was busy for %.0f s", settings.llm_queue_max_wait_seconds)
        metrics.error_code = "queue_timeout"
        yield Failed("queue_timeout", metrics)
        return
    except InferenceError as error:
        logger.warning("llm failed: %s", error.detail)
        metrics.error_code = "llm_failed"
        yield Failed("llm_failed", metrics)
        return

    sentences = len(answer)
    if not sentences:
        # the model answered with nothing usable; the child hears the fallback line
        metrics.error_code = "llm_failed"
        yield Failed("llm_failed", metrics)
        return

    metrics.total_ms = int(1000 * (time.perf_counter() - started))
    yield Finished(
        child_text=transcript.text,
        answer_text=" ".join(answer),
        sentences=sentences,
        metrics=metrics,
        model_id=model_id,
        prompt_version=str(built.version),
    )


async def _transcribe(
    inference: Inference, audio: bytes, language: Language, metrics: Metrics
) -> Transcript | Failed:
    try:
        transcript = await inference.stt.transcribe(audio, language=language)
    except InferenceError as error:
        logger.warning("stt failed: %s", error.detail)
        metrics.error_code = "stt_failed"
        return Failed("stt_failed", metrics)
    metrics.stt_ms = transcript.stt_ms
    metrics.stt_confidence = transcript.confidence
    if not transcript.text.strip() or transcript.no_speech_prob > NO_SPEECH_LIMIT:
        # the paw was held but nothing was said, or the room was too loud (UC-22)
        metrics.error_code = "stt_empty"
        return Failed("stt_empty", metrics)
    return transcript


async def _speak(
    inference: Inference, sentence: str, language: Language, metrics: Metrics, started: float
) -> Speech | None:
    """Synthesize one sentence, recording the two latencies that matter."""
    before = time.perf_counter()
    try:
        speech = await inference.tts.synthesize(sentence, language=language)
    except InferenceError as error:
        logger.warning("tts failed: %s", error.detail)
        return None
    if metrics.tts_first_ms is None:
        metrics.tts_first_ms = int(1000 * (time.perf_counter() - before))
        metrics.first_audio_ms = int(1000 * (time.perf_counter() - started))
    return speech


def _absorb(metrics: Metrics, usage: Usage) -> None:
    """Copy what the generation reported into the row that gets stored."""
    metrics.prompt_tokens = usage.prompt_tokens or metrics.prompt_tokens
    metrics.prompt_tokens_cached = usage.prompt_tokens_cached
    metrics.output_tokens = usage.output_tokens
    metrics.ttft_ms = usage.ttft_ms
    metrics.prefill_tps = usage.prefill_tps
    metrics.decode_tps = usage.decode_tps
    metrics.llm_total_ms = usage.llm_total_ms
    metrics.truncated = usage.truncated

#!/usr/bin/env python3
"""Measure first-audio latency over the real stack (docs/MILESTONES.md M2, EVALUATION.md §4.1).

    make bench                 # 20 turns per language
    make bench N=5 LANG=sr

Drives /ws/turns exactly as the toy screen will: a parent is registered, a child added,
child mode entered, and then each turn sends 20 ms PCM frames and waits for audio. The
numbers are therefore end to end, through the WebSocket, with the real models.

**What the child "says" is synthesized by our own TTS service**, because there are no
recordings of children yet. That makes these numbers a fair measure of *latency* and no
measure at all of *accuracy*: the Serbian voice mispronounces the language, so
speech-to-text is being fed something no child would say. Accuracy needs real
recordings - see docs/reports/M2.md.

Nothing is written to disk and no audio is kept (docs/CLAUDE.md §2).
"""

from __future__ import annotations

import argparse
import array
import asyncio
import io
import json
import os
import secrets
import statistics
import struct
import sys
import time
import wave
from dataclasses import dataclass, field

try:
    import httpx
    import websockets
except ModuleNotFoundError:  # pragma: no cover - depends how the script is invoked
    sys.exit(
        "httpx and websockets are needed.\n"
        "Run it through the backend environment:  make bench\n"
        "or:  cd services/api && uv run python ../../scripts/bench_turns.py"
    )

SAMPLE_RATE = 16_000
FRAME_MS = 20
PIN = "2468"

#: things a 5-year-old asks. Short, varied, and all answerable without a protected
#: category, since the router that handles those arrives in M3.
QUESTIONS: dict[str, list[str]] = {
    "sr": [
        "Zasto je nebo plavo?",
        "Kako lete ptice?",
        "Zasto pada sneg?",
        "Sta jedu dinosaurusi?",
        "Zasto mesec sija nocu?",
        "Kako rastu cvetovi?",
        "Zasto su slonovi veliki?",
        "Gde spavaju ribe?",
        "Zasto je more slano?",
        "Kako pcele prave med?",
    ],
    "en": [
        "Why is the sky blue?",
        "How do birds fly?",
        "Why does it snow?",
        "What did dinosaurs eat?",
        "Why does the moon shine at night?",
        "How do flowers grow?",
        "Why are elephants so big?",
        "Where do fish sleep?",
        "Why is the sea salty?",
        "How do bees make honey?",
    ],
}


@dataclass
class Turn:
    first_audio_ms: float | None = None
    total_ms: float = 0.0
    sentences: int = 0
    speech_ms: float = 0.0
    error: str | None = None


@dataclass
class Run:
    language: str
    turns: list[Turn] = field(default_factory=list)

    @property
    def good(self) -> list[Turn]:
        return [turn for turn in self.turns if turn.error is None and turn.first_audio_ms]


def resample_to_16k(wav_bytes: bytes) -> bytes:
    """Linear resampling to the rate the browser worklet will send (§6.1).

    Deliberately dependency-free: the point is to feed the pipeline the right shape of
    audio, and the browser's own AudioWorklet does the real resampling.
    """
    with wave.open(io.BytesIO(wav_bytes)) as handle:
        rate = handle.getframerate()
        samples = array.array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
    if rate == SAMPLE_RATE:
        return samples.tobytes()
    out = array.array("h")
    step = rate / SAMPLE_RATE
    position = 0.0
    last = len(samples) - 1
    while position < last:
        index = int(position)
        fraction = position - index
        left = samples[index]
        right = samples[min(index + 1, last)]
        out.append(int(left + (right - left) * fraction))
        position += step
    return out.tobytes()


async def _speech(client: httpx.AsyncClient, tts: str, text: str, language: str) -> bytes:
    response = await client.post(f"{tts}/synthesize", json={"text": text, "language": language})
    response.raise_for_status()
    return resample_to_16k(response.content)


async def _child_session(client: httpx.AsyncClient, api: str, mailpit: str, language: str) -> str:
    """A fresh family, so a benchmark never reuses another run's history."""
    device = "bench-" + secrets.token_hex(4)
    email = f"bench-{secrets.token_hex(5)}@example.com"
    registered = await client.post(
        f"{api}/api/v1/auth/register",
        json={
            "email": email,
            "password": "bench-password-123",
            "adult_confirmed": True,
            "consent_accepted": True,
            "locale": language,
        },
    )
    registered.raise_for_status()

    messages = (await client.get(f"{mailpit}/api/v1/messages")).json()
    newest = messages["messages"][0]["ID"]
    body = (await client.get(f"{mailpit}/api/v1/message/{newest}")).json()
    token = body["Text"].split("token=")[1].split()[0].strip().rstrip(").,")

    verified = await client.post(f"{api}/api/v1/auth/verify", json={"token": token, "device_id": device})
    verified.raise_for_status()
    headers = {"Authorization": f"Bearer {verified.json()['access_token']}"}

    (
        await client.post(f"{api}/api/v1/auth/pin", json={"pin": PIN, "pin_repeat": PIN}, headers=headers)
    ).raise_for_status()
    child = await client.post(
        f"{api}/api/v1/children",
        json={
            "nickname": "Mila",
            "age": 5,
            "language": language,
            "interests": ["animals"],
            "avatar_id": "avatar-01",
            "character_id": "bear",
        },
        headers=headers,
    )
    child.raise_for_status()
    entered = await client.post(f"{api}/api/v1/child-mode/enter", headers=headers)
    entered.raise_for_status()
    selected = await client.post(
        f"{api}/api/v1/child-mode/select",
        json={"child_id": child.json()["id"]},
        headers={"Authorization": f"Bearer {entered.json()['token']}"},
    )
    selected.raise_for_status()
    return str(selected.json()["token"])


async def _one_turn(socket: object, audio: bytes, label: str) -> Turn:
    send = socket.send  # type: ignore[attr-defined]
    recv = socket.recv  # type: ignore[attr-defined]

    await send(json.dumps({"type": "turn.start", "turn_id_client": label}))
    frame = SAMPLE_RATE * 2 * FRAME_MS // 1000
    for index, offset in enumerate(range(0, len(audio), frame), start=1):
        await send(struct.pack(">I", index) + audio[offset : offset + frame])
    released = time.perf_counter()
    await send(json.dumps({"type": "turn.end", "turn_id_client": label}))

    result = Turn()
    while True:
        message = await asyncio.wait_for(recv(), timeout=120)
        if isinstance(message, bytes):
            size = struct.unpack(">I", message[:4])[0]
            with wave.open(io.BytesIO(message[4 + size :])) as handle:
                result.speech_ms += 1000 * handle.getnframes() / handle.getframerate()
            result.sentences += 1
            if result.first_audio_ms is None:
                result.first_audio_ms = (time.perf_counter() - released) * 1000
            continue
        event = json.loads(message)
        if event["type"] == "error":
            result.error = str(event["code"])
            break
        if event["type"] == "turn.done":
            break
    result.total_ms = (time.perf_counter() - released) * 1000
    return result


async def measure(language: str, count: int, api: str, mailpit: str, tts: str) -> Run:
    run = Run(language=language)
    questions = QUESTIONS[language]
    async with httpx.AsyncClient(timeout=120.0) as client:
        token = await _child_session(client, api, mailpit, language)
        print(f"  preparing {count} utterances...", flush=True)
        audio = [
            await _speech(client, tts, questions[index % len(questions)], language) for index in range(count)
        ]

    url = api.replace("https://", "wss://").replace("http://", "ws://") + "/api/v1/ws/turns"
    async with websockets.connect(url, subprotocols=["bearer", token], max_size=None) as socket:
        for index, spoken in enumerate(audio, start=1):
            turn = await _one_turn(socket, spoken, f"bench-{index}")
            run.turns.append(turn)
            mark = turn.error or f"{turn.first_audio_ms:.0f} ms"
            print(f"  turn {index:>3}/{count}: {mark}", flush=True)
    return run


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def report(run: Run) -> None:
    good = run.good
    print(f"\n=== {run.language}: {len(good)} of {len(run.turns)} turns answered ===")
    if not good:
        codes = sorted({turn.error or "?" for turn in run.turns})
        print(f"  every turn failed: {', '.join(codes)}")
        return
    first = [turn.first_audio_ms or 0.0 for turn in good]
    print(f"  first audio   p50 {percentile(first, 0.5):7.0f} ms   p95 {percentile(first, 0.95):7.0f} ms")
    print(f"                min {min(first):7.0f} ms   max {max(first):7.0f} ms")
    total = [turn.total_ms for turn in good]
    print(f"  whole turn    p50 {percentile(total, 0.5):7.0f} ms   p95 {percentile(total, 0.95):7.0f} ms")
    sentences = [turn.sentences for turn in good]
    speech = [turn.speech_ms for turn in good]
    mean_speech_s = statistics.mean(speech) / 1000
    mean_sentences = statistics.mean(sentences)
    print(f"  answer        {mean_sentences:.1f} sentences, {mean_speech_s:.1f} s of speech on average")
    failures = [turn.error for turn in run.turns if turn.error]
    if failures:
        print(f"  failures      {', '.join(sorted(set(failures)))}")
    # NFR-02: p50 <= 4 s, p95 <= 6 s on the server profile
    verdict = "within" if percentile(first, 0.5) <= 4000 and percentile(first, 0.95) <= 6000 else "OUTSIDE"
    print(f"  NFR-02        {verdict} the target (p50 <= 4 s, p95 <= 6 s)")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=20, help="turns per language")
    parser.add_argument("--language", action="append", default=[], choices=["sr", "en"])
    parser.add_argument("--api", default=os.environ.get("BENCH_API", "http://localhost:8001"))
    parser.add_argument("--mailpit", default=os.environ.get("BENCH_MAILPIT", "http://localhost:8026"))
    parser.add_argument("--tts", default=os.environ.get("BENCH_TTS", "http://localhost:8092"))
    args = parser.parse_args()

    languages = args.language or ["sr", "en"]
    runs = []
    for language in languages:
        print(f"\n--- {language} ---", flush=True)
        runs.append(await measure(language, args.turns, args.api, args.mailpit, args.tts))
    for run in runs:
        report(run)
    print(
        "\nThe component breakdown per turn is in turn_metrics; these are the client's"
        "\nown measurements, taken from turn.end to the first audio frame."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

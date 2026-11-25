#!/usr/bin/env python3
"""Synthesize the offline fallback lines for the child screen (ARCHITECTURE.md §6.1).

    make audio

The child screen never shows text (docs/CLAUDE.md §2), so every failure has to be heard.
These three lines come from UI.md §5 and are played from local files, because the service
that would otherwise speak them may be the one that just failed.

**The output is not committed.** The only Serbian voice available is non-commercial
(docs/CLAUDE.md §3), so its audio may not live in the repository any more than its
weights may; and once the Serbian side is a recorded voice, these files are regenerated
anyway. apps/web/public/audio is therefore in .gitignore, and the screen copes with the
files being absent.

Needs the tts service running: `make dev`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

#: UI.md §5, verbatim. The keys are what apps/web/lib/audio/fallback.ts asks for.
LINES: dict[str, dict[str, str]] = {
    "sr": {
        "hold_paw": "Drži šapu dok pričaš, slušam te!",
        "not_heard": "Nisam te dobro čuo, možeš li još jednom?",
        "fallback": "Hmm, malo sam se umorio. Probaj opet!",
    },
    "en": {
        "hold_paw": "Hold my paw while you talk, I'm listening!",
        "not_heard": "I didn't quite hear you, can you say it again?",
        "fallback": "Hmm, I'm a bit sleepy. Try again!",
    },
}


def synthesize(tts: str, text: str, language: str) -> bytes:
    request = urllib.request.Request(
        f"{tts}/synthesize",
        data=json.dumps({"text": text, "language": language}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return bytes(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tts", default=os.environ.get("BENCH_TTS", "http://localhost:8092"))
    parser.add_argument("--dest", default="apps/web/public/audio", type=Path)
    args = parser.parse_args()

    written = 0
    for language, lines in LINES.items():
        folder = args.dest / language
        folder.mkdir(parents=True, exist_ok=True)
        for key, text in lines.items():
            try:
                wav = synthesize(args.tts, text, language)
            except urllib.error.HTTPError as error:
                if error.code == 503:
                    print(f"  ! {language}: no voice for this language, skipped")
                    break
                print(f"  ! {language}/{key}: {error}", file=sys.stderr)
                return 1
            except urllib.error.URLError as error:
                print(f"the tts service is not reachable at {args.tts} ({error})", file=sys.stderr)
                print("Start the stack first:  make dev", file=sys.stderr)
                return 2
            target = folder / f"{key}.wav"
            target.write_bytes(wav)
            print(f"  = {target} ({len(wav) // 1024} KB)")
            written += 1
    print(f"{written} file(s). Not committed, by design - see the module docstring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

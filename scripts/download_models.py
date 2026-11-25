#!/usr/bin/env python3
"""Download the model weights listed in models/registry.yaml.

Weights are never committed (docs/CLAUDE.md §3). This script fetches them into a local
directory and verifies sha256 when the registry has one.

Run it through the backend environment, which has PyYAML:

    make models
    cd services/api && uv run python ../../scripts/download_models.py --check

Weights are not needed for M1; the LLM/STT/TTS clients arrive in M2.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, NamedTuple

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - depends on how the script is invoked
    sys.exit(
        "PyYAML is not available.\n"
        "Run this through the backend environment:  make models\n"
        "or:  cd services/api && uv run python ../../scripts/download_models.py"
    )

HF_BASE = "https://huggingface.co"
CHUNK = 1024 * 1024
#: one try plus three retries, for connections that drop mid-file
ATTEMPTS = 4


class Entry(NamedTuple):
    kind: str
    model_id: str
    repo: str
    #: one or more paths inside the repo: a GGUF is a single file, while a CTranslate2
    #: model or a Piper voice is a set of files that are useless apart
    paths: list[str]
    #: expected sha256 per path, or None for a file that has not been verified yet
    hashes: dict[str, str | None]
    internal_only: bool
    gated: bool


def entries(registry: dict[str, Any]) -> list[Entry]:
    """Flatten the registry into one entry per model, each with the files it needs.

    `source.files` may be a plain list of paths, or a mapping of path -> sha256 once the
    weights have been fetched once and their digests recorded.
    """
    found: list[Entry] = []
    for kind in ("models", "stt", "tts"):
        for item in registry.get(kind) or []:
            source = item.get("source") or {}
            repo = source.get("repo")
            if not repo:
                continue
            listed = source.get("files")
            if isinstance(listed, dict):
                hashes: dict[str, str | None] = {str(k): (str(v) if v else None) for k, v in listed.items()}
            elif listed:
                hashes = {str(one): None for one in listed}
            else:
                single = str(source.get("path") or item.get("file") or "")
                expected = source.get("sha256")
                hashes = {single: (str(expected) if expected else None)} if single else {}
            found.append(
                Entry(
                    kind=kind,
                    model_id=str(item.get("id")),
                    repo=str(repo),
                    paths=list(hashes),
                    hashes=hashes,
                    internal_only=bool(item.get("internal_only")),
                    gated=bool(source.get("gated")),
                )
            )
    return found


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    """Fetch one file, retrying a dropped connection.

    These files are hundreds of megabytes, and a connection reset halfway through is
    ordinary rather than exceptional: one did, and the whole run stopped on a traceback.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    headers = {"User-Agent": "bruno-mvp-model-downloader"}
    # only needed for repositories whose licence must be accepted first (e.g. Gemma)
    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last: OSError | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            _stream(urllib.request.Request(url, headers=headers), partial)
            partial.replace(target)
            return
        except urllib.error.HTTPError:
            raise  # a 404 or a licence wall will not improve with another try
        except OSError as error:  # dropped connection, reset, timeout
            last = error
            partial.unlink(missing_ok=True)
            if attempt < ATTEMPTS:
                print(f"      connection lost ({type(error).__name__}), retrying {attempt}/{ATTEMPTS - 1}")
                time.sleep(2 * attempt)
    assert last is not None
    raise last


def _stream(request: urllib.request.Request, partial: Path) -> None:
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with partial.open("wb") as handle:
            while True:
                block = response.read(CHUNK)
                if not block:
                    break
                handle.write(block)
                done += len(block)
                if total:
                    sys.stdout.write(f"\r    {done / total:6.1%} ({done // 1048576} MB)")
                    sys.stdout.flush()
        if total and done < total:
            raise OSError(f"truncated: {done} of {total} bytes")
    sys.stdout.write("\r" + " " * 40 + "\r")


def handle(entry: Entry, dest: Path, *, check_only: bool) -> bool:
    if not entry.paths:
        print(f"  ! {entry.model_id}: no source.path or source.files in the registry, skipped")
        return False
    if entry.gated and not os.environ.get("HF_TOKEN", "").strip():
        print(f"  ! {entry.model_id}: gated repository; accept the terms at")
        print(f"      {HF_BASE}/{entry.repo}  then export HF_TOKEN and run again")
        return False
    ok = True
    for one in entry.paths:
        ok = _one_file(entry, one, dest, check_only=check_only) and ok
    return ok


def _one_file(entry: Entry, inside: str, dest: Path, *, check_only: bool) -> bool:
    # keep the repo's own layout, so a voice sits next to its .json and a CTranslate2
    # model keeps the file names its runtime looks for
    target = dest / entry.kind / entry.model_id / inside
    url = f"{HF_BASE}/{entry.repo}/resolve/main/{inside}"
    label = f"{entry.model_id}/{inside}" if len(entry.paths) > 1 else entry.model_id
    expected = entry.hashes.get(inside)

    if target.exists():
        actual = sha256_of(target)
        if expected and actual != expected:
            print(f"  ! {label}: sha256 mismatch")
            print(f"      expected {expected}")
            print(f"      actual   {actual}")
            return False
        if expected:
            print(f"  = {label}: present, sha256 ok")
        else:
            print(f"  = {label}: present; add to registry -> sha256: {actual}")
        return True

    if check_only:
        print(f"  - {label}: missing ({url})")
        return False

    print(f"  > {label}: downloading {entry.repo}/{inside}")
    try:
        download(url, target)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as error:
        print(f"  ! {label}: download failed ({error}).")
        print(f"      Some repositories require accepting a license first: {HF_BASE}/{entry.repo}")
        return False

    actual = sha256_of(target)
    if expected and actual != expected:
        print(f"  ! {label}: sha256 mismatch after download, discarding the file")
        target.unlink(missing_ok=True)
        return False
    if not expected:
        print(f"      sha256 {actual}  <- add this to models/registry.yaml")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="models/registry.yaml", type=Path)
    parser.add_argument("--dest", default=os.environ.get("MODEL_DIR", "models/weights"), type=Path)
    parser.add_argument("--only", action="append", default=[], help="model id (repeatable)")
    parser.add_argument("--check", action="store_true", help="only report what is missing")
    args = parser.parse_args()

    if not args.registry.exists():
        print(f"registry not found: {args.registry}", file=sys.stderr)
        return 2

    registry = yaml.safe_load(args.registry.read_text(encoding="utf-8")) or {}
    wanted = entries(registry)
    if args.only:
        wanted = [e for e in wanted if e.model_id in set(args.only)]
        if not wanted:
            print(f"no registry entry matches {args.only}", file=sys.stderr)
            return 2

    print(f"registry {args.registry} -> {args.dest}")
    ok = True
    for entry in wanted:
        if entry.internal_only:
            print(f"  i {entry.model_id}: internal_only — never ship this to a public demo URL")
        ok = handle(entry, args.dest, check_only=args.check) and ok
    print("done" if ok else "finished with problems")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

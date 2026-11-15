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


class Entry(NamedTuple):
    kind: str
    model_id: str
    repo: str
    path: str
    sha256: str | None
    internal_only: bool


def entries(registry: dict[str, Any]) -> list[Entry]:
    found: list[Entry] = []
    for kind in ("models", "stt", "tts"):
        for item in registry.get(kind) or []:
            source = item.get("source") or {}
            repo = source.get("repo")
            if not repo:
                continue
            found.append(
                Entry(
                    kind=kind,
                    model_id=str(item.get("id")),
                    repo=str(repo),
                    path=str(source.get("path") or item.get("file") or ""),
                    sha256=source.get("sha256"),
                    internal_only=bool(item.get("internal_only")),
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
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "bruno-mvp-model-downloader"})
    with urllib.request.urlopen(request) as response:  # noqa: S310 - fixed https host
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
    sys.stdout.write("\r" + " " * 40 + "\r")
    partial.replace(target)


def handle(entry: Entry, dest: Path, *, check_only: bool) -> bool:
    if not entry.path:
        print(f"  ! {entry.model_id}: no source.path in the registry, skipped")
        return True
    target = dest / entry.kind / entry.model_id / Path(entry.path).name
    url = f"{HF_BASE}/{entry.repo}/resolve/main/{entry.path}"

    if target.exists():
        actual = sha256_of(target)
        if entry.sha256 and actual != entry.sha256:
            print(f"  ! {entry.model_id}: sha256 mismatch\n      expected {entry.sha256}\n      actual   {actual}")
            return False
        if entry.sha256:
            print(f"  = {entry.model_id}: present, sha256 ok")
        else:
            print(f"  = {entry.model_id}: present; add to registry -> sha256: {actual}")
        return True

    if check_only:
        print(f"  - {entry.model_id}: missing ({url})")
        return False

    print(f"  > {entry.model_id}: downloading {entry.repo}/{entry.path}")
    try:
        download(url, target)
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        print(f"  ! {entry.model_id}: download failed ({error}).")
        print(f"      Some repositories require accepting a license first: {HF_BASE}/{entry.repo}")
        return False

    actual = sha256_of(target)
    if entry.sha256 and actual != entry.sha256:
        print(f"  ! {entry.model_id}: sha256 mismatch after download, removing file")
        target.unlink(missing_ok=True)
        return False
    if not entry.sha256:
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
            print(f"  i {entry.model_id}: internal_only (license unconfirmed) — never ship to a public demo URL")
        ok = handle(entry, args.dest, check_only=args.check) and ok
    print("done" if ok else "finished with problems")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Read models/registry.yaml and resolve a model's files on disk.

The registry is the only place a model is named (docs/CLAUDE.md §3, F-20). The three
inference images therefore resolve their weights through this module instead of carrying
a file name in a Dockerfile or a compose command: switching model is a registry edit.

Shared by the llm, stt and tts images; the build context is services/inference, so each
Dockerfile copies this file in.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

#: where compose mounts models/ (read-only); registry.yaml and weights/ live under it
MODEL_ROOT = Path(os.environ.get("MODEL_ROOT", "/srv/models"))


def registry() -> dict[str, Any]:
    path = Path(os.environ.get("MODEL_REGISTRY_PATH", MODEL_ROOT / "registry.yaml"))
    if not path.is_file():
        raise SystemExit(f"model registry not found: {path}")
    loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded


def entry(kind: str, model_id: str | None = None) -> dict[str, Any]:
    """One registry entry. Without an id, the first entry of that kind.

    `kind` is "models", "stt" or "tts", matching the registry's own top-level keys.
    """
    found = registry().get(kind) or []
    if not found:
        raise SystemExit(f"the registry lists no {kind} entries")
    if model_id is None:
        return dict(found[0])
    for item in found:
        if item.get("id") == model_id:
            return dict(item)
    known = ", ".join(str(item.get("id")) for item in found)
    raise SystemExit(f"no {kind} entry with id {model_id!r}; the registry has: {known}")


def default_llm() -> dict[str, Any]:
    """The active LLM: LLM_MODEL_ID if set, otherwise the registry's own `default`."""
    wanted = os.environ.get("LLM_MODEL_ID", "").strip() or registry().get("default")
    return entry("models", str(wanted))


def weights_dir(kind: str, model_id: str) -> Path:
    """Where scripts/download_models.py puts this entry's files."""
    return MODEL_ROOT / "weights" / kind / model_id


def weight_file(kind: str, model_id: str, name: str) -> Path:
    path = weights_dir(kind, model_id) / name
    if not path.exists():
        raise SystemExit(f"missing weights for {model_id}: {path}\nRun `make models` on the host first.")
    return path

"""Read models/registry.yaml (F-20, ARCHITECTURE.md §8).

The registry is the only place a model is named (docs/CLAUDE.md §3), so this module is
the only place the application learns which model it is talking to. Nothing here contains
a model id; `tests/test_registry.py::test_no_model_is_hard_coded_in_the_backend` enforces
that for the whole package.

Endpoints in the file are written as `${LLM_SERVER_URL}/v1` so one file serves both
inference profiles (§4); they are expanded from settings here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import Profile, settings

logger = logging.getLogger("app.inference.registry")

_PLACEHOLDER = re.compile(r"\$\{([A-Z_]+)\}")


class RegistryError(RuntimeError):
    """The registry is missing, unreadable, or does not describe what was asked for."""


@dataclass(frozen=True)
class LanguageModel:
    """One `models:` entry, with its endpoint already resolved for a profile."""

    id: str
    family: str
    context: int
    quant: str
    license: str
    endpoint: str
    #: per-family generation options, e.g. the switch that keeps thinking off (§6.3)
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def disables_thinking(self) -> bool:
        return self.options.get("enable_thinking") is False


@dataclass(frozen=True)
class SpeechModel:
    """One `stt:` or `tts:` entry."""

    id: str
    runtime: str
    license: str
    language: str | None = None
    internal_only: bool = False


def _expand(value: str) -> str:
    """Replace ${NAME} with the matching setting."""
    known = {
        "LLM_SERVER_URL": settings.llm_server_url,
        "STT_SERVER_URL": settings.stt_server_url,
        "TTS_SERVER_URL": settings.tts_server_url,
        "DEVICE_TUNNEL_URL": settings.device_tunnel_url,
    }

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in known:
            raise RegistryError(f"registry endpoint refers to unknown setting ${{{name}}}")
        resolved = known[name]
        if not resolved:
            raise RegistryError(f"{name} is empty, so this endpoint cannot be used")
        return resolved.rstrip("/")

    return _PLACEHOLDER.sub(replace, value)


@lru_cache
def document() -> dict[str, Any]:
    path = Path(settings.model_registry_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RegistryError(f"cannot read the model registry at {path}: {error}") from error
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise RegistryError(f"the model registry at {path} is not a mapping")
    return loaded


def reload() -> None:
    """Forget the parsed file. Used by tests and, from M6, by the admin registry screen."""
    document.cache_clear()


def _entries(kind: str) -> list[dict[str, Any]]:
    found = document().get(kind)
    if not isinstance(found, list) or not found:
        raise RegistryError(f"the model registry lists no {kind!r} entries")
    return [item for item in found if isinstance(item, dict)]


def language_model(*, profile: Profile | None = None, model_id: str | None = None) -> LanguageModel:
    """The model to generate with: `model_id` if given, else the registry's `default`.

    Only models whose `active_envs` include the running environment may be chosen, so a
    model listed for the benchmark alone cannot be served to a child by accident.
    """
    profile = profile or settings.inference_profile_default
    wanted = model_id or document().get("default")
    if not wanted:
        raise RegistryError("the model registry has no `default`")

    for item in _entries("models"):
        if item.get("id") != wanted:
            continue
        allowed = item.get("active_envs") or []
        if settings.environment not in allowed:
            raise RegistryError(
                f"{wanted!r} is not active in the {settings.environment!r} environment "
                f"(active_envs: {', '.join(map(str, allowed)) or 'none'})"
            )
        endpoints = item.get("endpoints") or {}
        if profile not in endpoints:
            raise RegistryError(f"{wanted!r} has no endpoint for the {profile!r} profile")
        return LanguageModel(
            id=str(item["id"]),
            family=str(item.get("family", "")),
            context=int(item.get("context", 2048)),
            quant=str(item.get("quant", "")),
            license=str(item.get("license", "")),
            endpoint=_expand(str(endpoints[profile])),
            options=dict(item.get("options") or {}),
        )
    known = ", ".join(str(item.get("id")) for item in _entries("models"))
    raise RegistryError(f"no model {wanted!r} in the registry; it lists: {known}")


def speech_to_text() -> SpeechModel:
    item = _entries("stt")[0]
    return SpeechModel(
        id=str(item["id"]),
        runtime=str(item.get("runtime", "")),
        license=str(item.get("license", "")),
    )


def voices() -> dict[str, SpeechModel]:
    """The TTS voice per language, keyed by language code."""
    found: dict[str, SpeechModel] = {}
    for item in _entries("tts"):
        language = item.get("language")
        if not language:
            continue
        found[str(language)] = SpeechModel(
            id=str(item["id"]),
            runtime=str(item.get("runtime", "")),
            license=str(item.get("license", "")),
            language=str(language),
            internal_only=bool(item.get("internal_only")),
        )
    return found

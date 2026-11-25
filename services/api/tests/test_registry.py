"""The model registry is the only place a model is named (F-20, docs/CLAUDE.md §3)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import REPO_ROOT

REGISTRY = REPO_ROOT / "models" / "registry.yaml"
APP_DIR = REPO_ROOT / "services" / "api" / "app"

#: the three models from docs/CLAUDE.md §3
EXPECTED_MODELS = {"qwen3-1.7b", "gemma3-1b", "qwen3-0.6b"}


@pytest.fixture(scope="module")
def registry() -> dict[str, Any]:
    if not REGISTRY.is_file():  # pragma: no cover - the api container mounts it elsewhere
        pytest.skip("registry is not available here")
    loaded: dict[str, Any] = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    return loaded


def test_registry_lists_the_three_models(registry: dict[str, Any]) -> None:
    ids = {model["id"] for model in registry["models"]}
    assert ids == EXPECTED_MODELS
    assert registry["default"] in ids


def test_every_model_carries_what_the_runtime_needs(registry: dict[str, Any]) -> None:
    for model in registry["models"]:
        for key in ("file", "quant", "size_mb", "context", "runtime", "license", "endpoints"):
            assert key in model, f"{model['id']} is missing {key}"
        # the toy's context limit (NFR-04); both profiles use the same value
        assert model["context"] == 2048
        assert model["size_mb"] <= 2048, "must fit the ~2 GB budget (D6)"
        assert {"server", "device"} <= set(model["endpoints"])


def test_qwen_thinking_is_disabled(registry: dict[str, Any]) -> None:
    """Qwen3 must not emit <think> blocks (ARCHITECTURE.md §6.3)."""
    for model in registry["models"]:
        if model["family"] == "qwen3":
            assert model["options"]["enable_thinking"] is False


def test_the_serbian_voice_stays_internal_only(registry: dict[str, Any]) -> None:
    """Its licence is unconfirmed, so it must never reach a public demo (docs/CLAUDE.md §3)."""
    serbian = [voice for voice in registry["tts"] if voice.get("language") == "sr"]
    assert serbian, "no Serbian voice in the registry"
    assert all(voice["internal_only"] is True for voice in serbian)


def test_no_model_is_hard_coded_in_the_backend() -> None:
    """A model id in application code would bypass the registry and the benchmark."""
    forbidden = ("qwen", "gemma", "kokoro", "piper", "whisper")
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {needle}")
    assert offenders == [], f"model names belong in the registry only: {offenders}"


def test_weights_are_not_committed() -> None:
    """Ask git, not the filesystem.

    `make models` puts real weights in models/weights/, so looking for files on disk
    failed the moment they were downloaded - which is the normal state of a working
    checkout, not a mistake. What must stay true is that git never tracks them.
    """
    listed = subprocess.run(
        ["git", "ls-files", "--", "models"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:  # pragma: no cover - not a git checkout (e.g. in a container)
        pytest.skip("not a git checkout")
    tracked = [
        name for name in listed.stdout.split() if name.endswith((".gguf", ".bin", ".pth", ".onnx", ".pt"))
    ]
    assert tracked == [], f"model weights must never be committed: {tracked}"
    assert "models/weights/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_registry_has_no_absolute_local_paths(registry: dict[str, Any]) -> None:
    """Endpoints are environment variables, so the same file works on both profiles."""
    for model in registry["models"]:
        for profile, endpoint in model["endpoints"].items():
            assert endpoint.startswith("${"), f"{model['id']}/{profile} is not configurable"


def test_registry_file_lives_outside_the_application_package() -> None:
    assert Path(REGISTRY).is_file()
    assert not (APP_DIR / "registry.yaml").exists()

"""Clients for the local inference services, behind one interface each.

No external AI API is ever called (docs/CLAUDE.md §2): these talk to the llm, stt and tts
containers, which run the local runtimes. Which model answers, and which runtime serves
it, is decided by models/registry.yaml alone (F-20) - deliberately not named here, so
that reading this package never tells you which model is in use.
"""

from __future__ import annotations

from app.inference.clients import (
    Generation,
    Inference,
    InferenceError,
    LanguageModelClient,
    Message,
    Speech,
    SpeechToText,
    TextToSpeech,
    Transcript,
    Usage,
)
from app.inference.registry import RegistryError

__all__ = [
    "Generation",
    "Inference",
    "InferenceError",
    "LanguageModelClient",
    "Message",
    "RegistryError",
    "Speech",
    "SpeechToText",
    "TextToSpeech",
    "Transcript",
    "Usage",
]

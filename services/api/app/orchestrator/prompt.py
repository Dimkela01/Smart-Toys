"""Assemble the prompt for one turn (DATA_MODEL.md §5).

Blocks go in the order the spec gives, stable parts first, so llama.cpp reuses its cached
prefix between turns of the same session - which is most of what makes the second answer
faster than the first. M2 fills blocks 1-3, 7 and 8; the parent rules line (4), memory
(5) and the activity step (6) arrive with M3, M5 and M4 and are left empty here.

Blocks 1-3 become one system message, because they do not change inside a session.
History becomes alternating user/assistant messages, and the child's new words are the
last user message.

Budgets are in tokens and this service has no tokenizer, so `estimate_tokens` works from
characters per token - measured against the real tokenizer, per language, because the two
languages are nowhere near each other (see _CHARS_PER_TOKEN). The exact count comes back
from the server in `usage.prompt_tokens` and is recorded in turn_metrics, so the estimate
is checked against reality on every turn rather than trusted.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import Language, settings
from app.inference import Message

logger = logging.getLogger("app.orchestrator.prompt")

#: token budgets from DATA_MODEL.md §5
BUDGET_SYSTEM = 400
BUDGET_CHARACTER = 40
BUDGET_CHILD = 60
BUDGET_HISTORY = 700
BUDGET_CHILD_MESSAGE = 80
BUDGET_TOTAL = 1610

#: Measured 2026-11-25 against the active model's own tokenizer (llama-server
#: /tokenize), on the prompt files as committed:
#:
#:     sr  1734 characters -> 713 tokens   (2.43 characters per token)
#:     en  1701 characters -> 405 tokens   (4.20 characters per token)
#:
#: Serbian costs about 1.7x more tokens than English for the same text, because the
#: tokenizer splits its diacritics and its endings far more finely. Two consequences
#: worth knowing before reading the numbers below:
#:
#: * Block 1 in Serbian is 713 tokens, not the <= 400 that DATA_MODEL.md §5 budgets. The
#:   total still fits (713 + 40 + 60 + 700 + 80 = 1593 <= 1610) and the safety rules are
#:   never trimmed to make a budget - see _truncate - so the code is correct and the
#:   documented line item is what is wrong. Raised for a decision, not silently changed.
#: * The 700-token history budget therefore holds noticeably fewer Serbian turns than
#:   English ones, so memory is effectively shorter in Serbian.
_CHARS_PER_TOKEN = {"sr": 2.43, "en": 4.20}
#: used where the language is not known; the pessimistic of the two
_CHARS_PER_TOKEN_DEFAULT = 2.43

#: §3.1: the window grows to 8 turns, then drops the oldest 4, so the cached prefix
#: changes rarely instead of on every turn
HISTORY_MAX_TURNS = 8
HISTORY_KEEP_TURNS = 4

#: answer length (§5); the story activity raises it in M4
MAX_ANSWER_TOKENS = 150

_COMMENT = re.compile(r"^#.*$", re.M)


def estimate_tokens(text: str, language: Language | None = None) -> int:
    """Approximate the token count of `text`, erring high.

    Exact counts arrive with the answer (`usage.prompt_tokens`); this is only for
    deciding how much history fits before the request is sent.
    """
    ratio = _CHARS_PER_TOKEN.get(language or "", _CHARS_PER_TOKEN_DEFAULT)
    return math.ceil(len(text) / ratio)


@dataclass(frozen=True)
class PromptVersion:
    """What `turns.prompt_version` records, so an answer can be traced to its prompt."""

    name: str
    sha256: str

    def __str__(self) -> str:
        return f"{self.name}@{self.sha256[:12]}"


@dataclass(frozen=True)
class Turn:
    """One past exchange, for block 7."""

    child_text: str
    answer_text: str


@dataclass(frozen=True)
class Child:
    """Everything block 3 needs. A nickname, never a full name (UC-03)."""

    nickname: str
    age: int
    language: Language
    interests: tuple[str, ...] = ()


@dataclass(frozen=True)
class Character:
    """Block 2: who is speaking (content/characters.json)."""

    name: str
    personality: str


@dataclass(frozen=True)
class Prompt:
    messages: list[Message]
    version: PromptVersion
    estimated_tokens: int
    #: how many past turns were left out to fit the budget
    dropped_turns: int


def prompts_dir() -> Path:
    return Path(settings.prompts_dir)


@lru_cache
def system_block(language: Language, version: int = 1) -> tuple[str, PromptVersion]:
    """Block 1, with the comment header stripped."""
    name = f"system_v{version}_{language}.txt"
    path = prompts_dir() / name
    raw = path.read_text(encoding="utf-8")
    body = _COMMENT.sub("", raw).strip()
    if not body:
        raise RuntimeError(f"{path} has no prompt text")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return body, PromptVersion(name=name, sha256=digest)


def reload() -> None:
    """Forget the cached prompt files (tests; the admin prompt screen in M6)."""
    system_block.cache_clear()


def _child_block(child: Child) -> str:
    """Block 3. Interests are the child's own words, so they are passed through as given."""
    if child.language == "sr":
        line = f"DETE: {child.nickname}, {child.age} godina."
        if child.interests:
            line += f" Voli: {', '.join(child.interests)}."
    else:
        line = f"CHILD: {child.nickname}, aged {child.age}."
        if child.interests:
            line += f" Likes: {', '.join(child.interests)}."
    return line


def _character_block(character: Character) -> str:
    return character.personality.strip()


def build(
    *,
    child: Child,
    character: Character,
    child_message: str,
    history: list[Turn] | None = None,
    version: int = 1,
) -> Prompt:
    """Assemble the prompt for one turn.

    History is trimmed from the oldest first; blocks 1-4 are never dropped (§5).
    """
    body, prompt_version = system_block(child.language, version)
    system = body.format(
        character_name=character.name,
        child_name=child.nickname,
        child_age=child.age,
    )

    language = child.language
    character_line = _truncate(_character_block(character), BUDGET_CHARACTER, "character", language)
    child_line = _truncate(_child_block(child), BUDGET_CHILD, "child", language)
    said = _truncate(child_message.strip(), BUDGET_CHILD_MESSAGE, "child message", language)

    system_text = "\n\n".join(part for part in (system, character_line, child_line) if part)
    fixed_tokens = estimate_tokens(system_text, language) + estimate_tokens(said, language)

    kept = list(history or [])[-HISTORY_MAX_TURNS:]
    dropped = len(history or []) - len(kept)
    while kept and (
        estimate_tokens(_history_text(kept), language) > BUDGET_HISTORY
        or fixed_tokens + estimate_tokens(_history_text(kept), language) > BUDGET_TOTAL
    ):
        kept.pop(0)
        dropped += 1

    messages = [Message("system", system_text)]
    for turn in kept:
        messages.append(Message("user", turn.child_text))
        messages.append(Message("assistant", turn.answer_text))
    messages.append(Message("user", said))

    total = sum(estimate_tokens(message.content, language) for message in messages)
    if total > BUDGET_TOTAL:
        # Blocks 1-4 may not be dropped (§5), so with no history left to trim there is
        # nothing to do here but say so: a prompt file has grown and the file is what has
        # to change. The hard limit is the model's context, checked by the caller.
        logger.warning(
            "prompt is over the §5 budget: ~%d tokens against %d (%s, %d history turns)",
            total,
            BUDGET_TOTAL,
            language,
            len(kept),
        )
    return Prompt(
        messages=messages,
        version=prompt_version,
        estimated_tokens=total,
        dropped_turns=dropped,
    )


def _history_text(turns: list[Turn]) -> str:
    return "\n".join(f"{turn.child_text}\n{turn.answer_text}" for turn in turns)


def _truncate(text: str, budget: int, what: str, language: Language) -> str:
    """Cut a block to its budget.

    Deliberately never applied to block 1: half a rule list is more dangerous than a
    long one, so the safety prompt is sent whole and history gives way instead.
    """
    if estimate_tokens(text, language) <= budget:
        return text
    limit = int(budget * _CHARS_PER_TOKEN.get(language, _CHARS_PER_TOKEN_DEFAULT))
    logger.warning("%s block is over its %d-token budget, cut to %d characters", what, budget, limit)
    return text[:limit].rstrip()

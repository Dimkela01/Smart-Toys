"""Prompt assembly (DATA_MODEL.md §5).

These tests are about the *shape* of the prompt, which is what the model's behaviour and
the cache hit rate both depend on: stable blocks first, one system message, history as
alternating turns, the child's words last, and the oldest history dropped when the
budget runs out.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.orchestrator import prompt as builder
from app.orchestrator.prompt import Character, Child, Turn

BEAR = Character(name="Bruno", personality="Topao i radoznao meda koji voli da hvali dete.")
MILA = Child(nickname="Mila", age=5, language="sr", interests=("životinje", "svemir"))
SAM = Child(nickname="Sam", age=7, language="en", interests=("dinosaurs",))


@pytest.fixture(autouse=True)
def _fresh_prompts() -> Iterator[None]:
    builder.reload()
    yield
    builder.reload()


def test_both_languages_have_a_prompt_file_and_it_carries_its_own_version() -> None:
    for language in ("sr", "en"):
        body, version = builder.system_block(language)
        assert body, f"{language} prompt is empty"
        # the comment header explaining where the file came from must not reach the model
        assert "docs/SAFETY.md" not in body
        assert not body.startswith("#")
        assert version.name == f"system_v1_{language}.txt"
        assert len(version.sha256) == 64


def test_the_system_prompt_still_leaves_room_for_a_conversation() -> None:
    """Block 1 is bigger than DATA_MODEL.md §5 budgets it, and knowingly so.

    Measured against the model's own tokenizer, the Serbian prompt is 713 tokens against
    the documented <= 400 (English is 405). The safety rules are never trimmed to make a
    budget, so what this test guards is the thing that would actually break: that block 1
    plus the other fixed blocks plus an answer still leave room for history inside §5's
    total. If someone adds a paragraph to the prompt, this fails before a child meets a
    prompt with no memory in it.
    """
    for language in ("sr", "en"):
        body, _ = builder.system_block(language)
        fixed = builder.estimate_tokens(body, language)
        fixed += builder.BUDGET_CHARACTER + builder.BUDGET_CHILD + builder.BUDGET_CHILD_MESSAGE
        room_for_history = builder.BUDGET_TOTAL - fixed
        assert room_for_history >= builder.BUDGET_HISTORY, (
            f"{language}: block 1 has grown to ~{builder.estimate_tokens(body, language)} tokens, "
            f"leaving only {room_for_history} for history"
        )


def test_the_child_and_character_are_filled_in_and_no_placeholder_survives() -> None:
    built = builder.build(child=MILA, character=BEAR, child_message="Zasto je nebo plavo?")
    system = built.messages[0].content
    assert "Bruno" in system
    assert "Mila" in system
    assert "5" in system
    # an unfilled {placeholder} would be read aloud as part of the rules
    assert "{" not in system and "}" not in system


def test_the_blocks_are_one_system_message_in_the_order_the_spec_gives() -> None:
    built = builder.build(child=MILA, character=BEAR, child_message="Zdravo!")
    assert [message.role for message in built.messages] == ["system", "user"]
    system = built.messages[0].content
    assert system.index("Bruno") < system.index(BEAR.personality)
    assert system.index(BEAR.personality) < system.index("DETE: Mila")


def test_the_child_block_is_written_in_the_child_s_language() -> None:
    serbian = builder.build(child=MILA, character=BEAR, child_message="x").messages[0].content
    english = builder.build(child=SAM, character=BEAR, child_message="x").messages[0].content
    assert "DETE: Mila, 5 godina." in serbian
    assert "Voli: životinje, svemir." in serbian
    assert "CHILD: Sam, aged 7." in english
    assert "Likes: dinosaurs." in english


def test_a_child_with_no_interests_gets_no_empty_list() -> None:
    quiet = Child(nickname="Ana", age=4, language="sr")
    system = builder.build(child=quiet, character=BEAR, child_message="x").messages[0].content
    assert "DETE: Ana, 4 godina." in system
    assert "Voli:" not in system


def test_history_becomes_alternating_turns_and_the_child_speaks_last() -> None:
    history = [Turn("Zdravo", "Zdravo, Mila!"), Turn("Kako si?", "Odlicno!")]
    built = builder.build(child=MILA, character=BEAR, child_message="Zasto je nebo plavo?", history=history)
    assert [message.role for message in built.messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert built.messages[-1].content == "Zasto je nebo plavo?"
    assert built.dropped_turns == 0


def test_only_the_last_eight_turns_are_kept() -> None:
    """§3.1: the window holds at most 8 turns."""
    history = [Turn(f"pitanje {i}", f"odgovor {i}") for i in range(12)]
    built = builder.build(child=MILA, character=BEAR, child_message="x", history=history)
    assert built.dropped_turns >= 4
    kept = [message.content for message in built.messages if message.role == "assistant"]
    assert "odgovor 11" in kept
    assert "odgovor 0" not in kept


def test_a_long_history_is_trimmed_from_the_oldest_first() -> None:
    """Never blocks 1-4; always the oldest exchange (§5)."""
    long_answer = "rec " * 200
    history = [Turn(f"pitanje {i}", long_answer) for i in range(8)]
    built = builder.build(child=MILA, character=BEAR, child_message="x", history=history)
    assert built.dropped_turns > 0
    assert built.estimated_tokens <= builder.BUDGET_TOTAL
    # the system block survived the trimming
    assert "Bruno" in built.messages[0].content
    kept = [m.content for m in built.messages if m.role == "user" and m.content.startswith("pitanje")]
    if kept:
        newest = max(int(text.split()[1]) for text in kept)
        assert newest == 7, "the newest exchange must be the one that stays"


def test_a_very_long_utterance_is_cut_to_its_budget() -> None:
    """A 15-second press can hold more words than block 8 allows."""
    built = builder.build(child=MILA, character=BEAR, child_message="rec " * 500)
    assert builder.estimate_tokens(built.messages[-1].content) <= builder.BUDGET_CHILD_MESSAGE


def test_an_overlong_personality_line_is_cut_to_its_budget() -> None:
    """content/characters.json is reviewed by hand, so this is a guard, not a workflow."""
    chatty = Character(name="Bruno", personality="veoma dugacka licnost " * 50)
    system = builder.build(child=MILA, character=chatty, child_message="x").messages[0].content
    assert "Bruno" in system, "the character's name must survive the cut"
    # the personality line is in the system message, so measure what was added to it
    plain = builder.build(child=MILA, character=BEAR, child_message="x").messages[0].content
    added = builder.estimate_tokens(system, "sr") - builder.estimate_tokens(plain, "sr")
    assert added <= builder.BUDGET_CHARACTER


def test_the_safety_rules_are_never_trimmed_to_fit() -> None:
    """Half a rule list is more dangerous than a long one: history gives way instead."""
    history = [Turn("rec " * 300, "rec " * 300) for _ in range(8)]
    built = builder.build(child=MILA, character=BEAR, child_message="x", history=history)
    body, _ = builder.system_block("sr")
    first_rule = body.splitlines()[0].format(character_name="Bruno", child_name="Mila", child_age=5)
    last_rule = [line for line in body.splitlines() if line.startswith("- ")][-1]
    system = built.messages[0].content
    assert first_rule in system
    assert last_rule.format(character_name="Bruno") in system
    assert built.dropped_turns == 8, "every history turn should go before the prompt does"


def test_the_version_is_stable_for_the_same_file_and_differs_by_language() -> None:
    first = builder.build(child=MILA, character=BEAR, child_message="a").version
    second = builder.build(child=MILA, character=BEAR, child_message="b").version
    english = builder.build(child=SAM, character=BEAR, child_message="a").version
    assert first == second
    assert first.sha256 != english.sha256


# --- the estimate against the real tokenizer ---------------------------------------


async def test_the_measured_ratios_still_match_the_active_model() -> None:
    """Keep _CHARS_PER_TOKEN honest.

    The ratios in prompt.py were measured against one model's tokenizer. Change the
    model and they can drift, and the first symptom would be a prompt that overflows the
    context on a long Serbian session - a bad way to find out. This test asks the live
    service and skips when it is not running, so `make test-api` stays independent of
    the inference stack while `make test` with the full stack up does check it.
    """
    import httpx

    from app.config import settings

    url = f"{settings.llm_server_url.rstrip('/')}/tokenize"
    for language in ("sr", "en"):
        body, _ = builder.system_block(language)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json={"content": body})
                response.raise_for_status()
                real = len(response.json()["tokens"])
        except (httpx.HTTPError, KeyError) as error:
            pytest.skip(f"the llm service is not reachable at {url} ({error})")

        estimated = builder.estimate_tokens(body, language)
        # the estimate must not be optimistic, or history is sized against a prompt
        # smaller than the one actually sent
        assert estimated >= real, f"{language}: estimated {estimated} but the model counts {real}"
        assert estimated <= real * 1.25, (
            f"{language}: estimated {estimated} against {real} real tokens - too pessimistic, "
            "which throws away history that would have fitted"
        )

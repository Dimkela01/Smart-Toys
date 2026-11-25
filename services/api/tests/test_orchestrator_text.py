"""The think filter and the sentence splitter.

Both run on a token stream, so every test here feeds the text in pieces - including
pieces that cut a tag or a sentence in half, which is the case that matters and the one
a whole-string implementation gets wrong.
"""

from __future__ import annotations

import pytest

from app.orchestrator.text import SentenceStream, ThinkFilter


def _stream(filter_: ThinkFilter, text: str, *, size: int = 1) -> str:
    """Feed `text` in pieces of `size` characters, as a model would."""
    out = [filter_.feed(text[i : i + size]) for i in range(0, len(text), size)]
    out.append(filter_.close())
    return "".join(out)


# --- the think filter --------------------------------------------------------------


def test_text_without_tags_passes_through_unchanged() -> None:
    assert _stream(ThinkFilter(), "Nebo je plavo. Hoces da pricamo?") == "Nebo je plavo. Hoces da pricamo?"


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_a_think_block_is_removed_however_the_stream_is_cut(size: int) -> None:
    """The tag will not arrive whole: this is why the filter is incremental."""
    raw = "<think>The child asked about the sky.</think>Nebo je plavo!"
    assert _stream(ThinkFilter(), raw, size=size) == "Nebo je plavo!"


def test_text_before_a_think_block_is_kept() -> None:
    raw = "Pa, <think>hmm</think>nebo je plavo."
    assert _stream(ThinkFilter(), raw, size=2) == "Pa, nebo je plavo."


def test_several_blocks_are_all_removed() -> None:
    raw = "A<think>1</think>B<think>2</think>C"
    assert _stream(ThinkFilter(), raw, size=1) == "ABC"


def test_an_unclosed_block_swallows_the_rest_rather_than_leaking_it() -> None:
    """Safe direction: the child hears the fallback line, never the reasoning."""
    out = _stream(ThinkFilter(), "Dobro. <think>I should think about this at length")
    assert out == "Dobro. "


def test_a_lone_angle_bracket_is_not_mistaken_for_a_tag() -> None:
    assert _stream(ThinkFilter(), "3 < 5 je tacno.", size=1) == "3 < 5 je tacno."


def test_a_partial_tag_is_held_back_and_not_emitted_early() -> None:
    """The filter must not pass "<thi" through and then have to take it back."""
    filter_ = ThinkFilter()
    assert filter_.feed("Nebo <thi") == "Nebo "
    assert filter_.feed("nk>secret</think> je plavo.") == " je plavo."
    assert filter_.close() == ""


# --- the sentence splitter ---------------------------------------------------------


def test_a_sentence_is_emitted_as_soon_as_it_is_whole() -> None:
    """This is the latency win: sentence one goes to the voice while two is written."""
    stream = SentenceStream()
    assert stream.feed("Nebo je plavo. ") == ["Nebo je plavo."]
    assert stream.feed("Sunce greje") == []
    assert stream.close() == ["Sunce greje"]


@pytest.mark.parametrize("mark", [".", "!", "?", "…"])
def test_each_ending_mark_closes_a_sentence_and_is_kept(mark: str) -> None:
    """The voice needs the punctuation for intonation, so it stays on the sentence."""
    stream = SentenceStream()
    assert stream.feed(f"Zdravo{mark} ") == [f"Zdravo{mark}"]


def test_a_decimal_point_does_not_end_a_sentence() -> None:
    stream = SentenceStream()
    assert stream.feed("Zmaj je 3.5 metara dug. ") == ["Zmaj je 3.5 metara dug."]


def test_a_line_break_ends_a_sentence() -> None:
    stream = SentenceStream()
    assert stream.feed("Prvo ovo\nPa ovo. ") == ["Prvo ovo", "Pa ovo."]


def test_character_by_character_gives_the_same_sentences() -> None:
    text = "Nebo je plavo! Zasto pitas? Hajde da pricamo o suncu."
    stream = SentenceStream()
    found: list[str] = []
    for char in text:
        found.extend(stream.feed(char))
    found.extend(stream.close())
    assert found == ["Nebo je plavo!", "Zasto pitas?", "Hajde da pricamo o suncu."]


def test_sentences_are_counted_so_playback_can_be_ordered() -> None:
    stream = SentenceStream()
    stream.feed("Jedan. Dva. ")
    assert stream.count == 2
    stream.feed("Tri")
    stream.close()
    assert stream.count == 3


def test_trailing_whitespace_alone_is_not_a_sentence() -> None:
    stream = SentenceStream()
    stream.feed("Gotovo. ")
    assert stream.feed("  \n ") == []
    assert stream.close() == []

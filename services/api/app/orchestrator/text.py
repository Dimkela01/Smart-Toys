"""Turning a token stream into sentences that can be spoken (ARCHITECTURE.md §6.1, §6.3).

Both classes here are incremental on purpose. The child waits for *first audio*, not for
the whole answer (NFR-01), so the first sentence has to leave for the voice while the
model is still writing the second. Being incremental also means both have to cope with a
piece arriving in the middle of a word - or in the middle of a tag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Thinking is disabled through the registry (§6.3), but a model can still emit the tag
#: after a template change or a model swap. Stripping it is the defensive half: a child
#: must never hear the model reasoning out loud.
THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"

#: the longest prefix of either tag that might still be completed by the next piece
_PARTIAL = max(len(THINK_OPEN), len(THINK_CLOSE)) - 1

#: end of sentence: . ! ? … or a line break. A dot between digits is not an end, so
#: "3.5 metara" stays one sentence; neither language writes decimals any other way.
_END = re.compile(r"(?<!\d)([.!?…]+)(?=\s|$)|(\n+)")

#: a fragment this short is not worth a synthesis call of its own
MIN_SENTENCE_CHARS = 2


class ThinkFilter:
    """Remove <think>...</think> from a stream, however the pieces are cut.

    Text before an opening tag is passed through. Everything from an opening tag to its
    close is dropped, including the tags. An unclosed tag swallows the rest of the
    answer, which is the safe direction: the fallback line plays instead of reasoning.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    @property
    def inside_thinking(self) -> bool:
        return self._inside

    def feed(self, piece: str) -> str:
        """Add a piece and return whatever is now certainly outside the tags."""
        self._buffer += piece
        out: list[str] = []
        while self._buffer:
            if self._inside:
                index = self._buffer.find(THINK_CLOSE)
                if index == -1:
                    self._buffer = self._tail(THINK_CLOSE)
                    break
                self._buffer = self._buffer[index + len(THINK_CLOSE) :]
                self._inside = False
                continue
            index = self._buffer.find(THINK_OPEN)
            if index == -1:
                safe = len(self._buffer) - len(self._tail(THINK_OPEN))
                out.append(self._buffer[:safe])
                self._buffer = self._buffer[safe:]
                break
            out.append(self._buffer[:index])
            self._buffer = self._buffer[index + len(THINK_OPEN) :]
            self._inside = True
        return "".join(out)

    def close(self) -> str:
        """Flush. Anything still buffered inside a tag is dropped."""
        if self._inside:
            self._buffer = ""
            return ""
        remainder, self._buffer = self._buffer, ""
        return remainder

    def _tail(self, tag: str) -> str:
        """The trailing part of the buffer that could still become `tag`."""
        for size in range(min(_PARTIAL, len(self._buffer)), 0, -1):
            if tag.startswith(self._buffer[-size:]):
                return self._buffer[-size:]
        return ""


@dataclass
class SentenceStream:
    """Collect pieces and hand back whole sentences as soon as each one is whole.

    `feed` returns the sentences that completed with this piece, in order; `close`
    returns whatever is left. Sentences keep their punctuation, because the voice needs
    it for intonation.
    """

    _buffer: str = ""
    _emitted: int = field(default=0, init=False)

    @property
    def count(self) -> int:
        """How many sentences have been handed out, so the client can order playback."""
        return self._emitted

    def feed(self, piece: str) -> list[str]:
        self._buffer += piece
        found: list[str] = []
        while True:
            match = _END.search(self._buffer)
            if match is None:
                break
            sentence = self._buffer[: match.end()].strip()
            self._buffer = self._buffer[match.end() :].lstrip()
            if len(sentence) >= MIN_SENTENCE_CHARS:
                found.append(sentence)
                self._emitted += 1
            elif sentence and found:
                # a stray "!" after a sentence belongs to the sentence before it
                found[-1] += sentence
        return found

    def close(self) -> list[str]:
        remainder, self._buffer = self._buffer.strip(), ""
        if len(remainder) < MIN_SENTENCE_CHARS:
            return []
        self._emitted += 1
        return [remainder]

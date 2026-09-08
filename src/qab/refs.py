"""Reference grammar: word locations, spans, formulas, and the tokens the scorer matches on.

A truth instance or a claim word becomes one token. Quran tokens are
`("q", chapter, ordinal)`, formula tokens `("f", kind, k)`. Matching compares
`match_key(token)`, which folds the Hafs Basmala class (al-Fatiha 1:1:1-4 and
`Basmala:1-4`) onto one key so either label matches either kind of instance.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from . import hafs

FORMULAS: dict[str, int] = {"Basmala": 4, "Isti'adha": 5}
BASMALA = "Basmala"

_LOCATION = re.compile(r"^(\d+):(\d+):(\d+)$")
_SPAN = re.compile(r"^(\d+):(\d+):(\d+)-(\d+):(\d+):(\d+)$")
_FORMULA_WORD = re.compile(r"^(Basmala|Isti'adha):(\d+)$")

Token = tuple  # ("q", chapter, ordinal) | ("f", kind, k)


class Location(NamedTuple):
    chapter: int
    verse: int
    word: int

    def __str__(self) -> str:
        return f"{self.chapter}:{self.verse}:{self.word}"

    @property
    def ordinal(self) -> int:
        return hafs.ordinal(self.chapter, self.verse, self.word)


class Span(NamedTuple):
    start: Location
    end: Location

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"

    @property
    def chapter(self) -> int:
        return self.start.chapter

    def tokens(self) -> list[Token]:
        return [("q", self.chapter, o) for o in range(self.start.ordinal, self.end.ordinal + 1)]


def parse_location(text: str) -> Location:
    m = _LOCATION.match(text)
    if not m:
        raise ValueError(f"not a word location S:A:W: {text!r}")
    loc = Location(int(m[1]), int(m[2]), int(m[3]))
    if not hafs.valid(*loc):
        raise ValueError(f"word location out of range for Hafs: {text!r}")
    return loc


def parse_span(text: str) -> Span:
    """Strict `S:A:W-S:A:W`: one chapter, start ordinal <= end ordinal. No shorthand."""
    m = _SPAN.match(text)
    if not m:
        raise ValueError(f"reference must be a full word span S:A:W-S:A:W, Basmala, Isti'adha or null: {text!r}")
    start = parse_location(f"{m[1]}:{m[2]}:{m[3]}")
    end = parse_location(f"{m[4]}:{m[5]}:{m[6]}")
    if start.chapter != end.chapter:
        raise ValueError(f"a span stays within one chapter: {text!r}")
    if end.ordinal < start.ordinal:
        raise ValueError(f"span end precedes its start: {text!r}")
    return Span(start, end)


def truth_token(word: str) -> Token:
    """Token for a ground-truth `word` label (`S:A:W`, `Basmala:k`, `Isti'adha:k`)."""
    m = _FORMULA_WORD.match(word)
    if m:
        kind, k = m[1], int(m[2])
        if not 1 <= k <= FORMULAS[kind]:
            raise ValueError(f"{kind} has {FORMULAS[kind]} words: {word!r}")
        return ("f", kind, k)
    loc = parse_location(word)
    return ("q", loc.chapter, loc.ordinal)


def claim_tokens(reference: str | None) -> list[Token]:
    """Expand a submission reference into its claim tokens (empty for null)."""
    if reference is None:
        return []
    if reference in FORMULAS:
        return [("f", reference, k) for k in range(1, FORMULAS[reference] + 1)]
    return parse_span(reference).tokens()


def is_span(reference: str | None) -> bool:
    return reference is not None and reference not in FORMULAS


def match_key(token: Token) -> tuple:
    """Equality key for matching; folds the Basmala class onto one key."""
    if token[0] == "q" and token[1] == 1 and token[2] < FORMULAS[BASMALA]:
        return ("b", token[2] + 1)
    if token[0] == "f" and token[1] == BASMALA:
        return ("b", token[2])
    return token


def in_basmala_class(token: Token) -> bool:
    return match_key(token)[0] == "b"


def token_label(token: Token) -> str:
    if token[0] == "f":
        return f"{token[1]}:{token[2]}"
    return str(Location(*hafs.location(token[1], token[2])))

"""Hafs verse and word counts, bundled so the scorer has no external text dependency.

`data/hafs.json` holds, per chapter, the English name and the word count of every
verse in the Hafs ʿan ʿĀṣim reading (6236 verses, 77,433 words).
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

CHAPTERS = 114


@lru_cache(maxsize=1)
def _table() -> list[dict]:
    text = resources.files("qab").joinpath("data/hafs.json").read_text(encoding="utf-8")
    table = json.loads(text)
    if len(table) != CHAPTERS:
        raise RuntimeError("bundled Hafs table is corrupt")
    return table


def chapter_name(chapter: int) -> str:
    return _table()[chapter - 1]["name_en"]


def verse_count(chapter: int) -> int:
    return len(_table()[chapter - 1]["ayah_word_counts"])


def word_count(chapter: int, verse: int) -> int:
    return _table()[chapter - 1]["ayah_word_counts"][verse - 1]


def chapter_word_count(chapter: int) -> int:
    return sum(_table()[chapter - 1]["ayah_word_counts"])


@lru_cache(maxsize=CHAPTERS)
def _verse_offsets(chapter: int) -> tuple[int, ...]:
    offsets, total = [], 0
    for count in _table()[chapter - 1]["ayah_word_counts"]:
        offsets.append(total)
        total += count
    return tuple(offsets)


def ordinal(chapter: int, verse: int, word: int) -> int:
    """Zero-based position of a word within its chapter."""
    return _verse_offsets(chapter)[verse - 1] + word - 1


def location(chapter: int, ordinal_: int) -> tuple[int, int, int]:
    """Inverse of `ordinal`: (chapter, verse, word)."""
    offsets = _verse_offsets(chapter)
    lo, hi = 0, len(offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if offsets[mid] <= ordinal_:
            lo = mid
        else:
            hi = mid - 1
    return chapter, lo + 1, ordinal_ - offsets[lo] + 1


def valid(chapter: int, verse: int, word: int) -> bool:
    return (1 <= chapter <= CHAPTERS and 1 <= verse <= verse_count(chapter)
            and 1 <= word <= word_count(chapter, verse))

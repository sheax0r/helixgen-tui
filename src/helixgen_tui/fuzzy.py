"""Scored fuzzy matching for list filtering.

Pure — no Textual, no Rich. The ordered-subsequence gate is a strict superset
of a contiguous-substring match, so anything that matched the old boolean
filter still matches here. Scores are only meaningful when comparing results
of the *same* query; never compare scores across different queries.

Matching searches for the *best-scoring* alignment, not the leftmost one. A
greedy left-to-right walk would score "rh" against "Crunch Rhythm" on the
``r`` of "Crunch" and never see the word-boundary hit in "Rhythm", so the
boundary and contiguity bonuses would be unreachable for most real names.
Names are short, so the memoised search is cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

_SEPARATORS = " -_/.()[]"

# Relative weights. Tuned for "type part of a name"; tests assert ordering, not values.
_CONTIGUOUS_BONUS = 8
_BOUNDARY_BONUS = 6
_PREFIX_BONUS = 10
_POSITION_PENALTY = 1
_UNMATCHED_TAIL_PENALTY = 1
_MAX_POSITION_PENALTY = 20


@dataclass(frozen=True)
class Match:
    """A successful match.

    ``score`` ranks results of one query (higher = better); ``indices`` are the
    positions in the original text of the matched characters, strictly
    increasing, for highlighting.
    """

    score: int
    indices: tuple[int, ...]


def match(query: str, text: str) -> Match | None:
    """Case-insensitive ordered-subsequence match with relevance scoring.

    Returns ``None`` when ``query`` is not a subsequence of ``text``. An empty
    query returns ``Match(0, ())`` — matches everything, native order preserved.
    """
    if not query:
        return Match(score=0, indices=())

    lowered_query = query.lower()
    lowered_text = text.lower()

    def placement_score(index: int) -> int:
        """Score of matching a character at ``index``, ignoring its predecessor."""
        score = -min(index, _MAX_POSITION_PENALTY) * _POSITION_PENALTY
        if index == 0:
            score += _PREFIX_BONUS
        elif lowered_text[index - 1] in _SEPARATORS:
            score += _BOUNDARY_BONUS
        return score

    @lru_cache(maxsize=None)
    def best_from(query_pos: int, index: int) -> tuple[int, tuple[int, ...]] | None:
        """Best score and indices for matching ``query[query_pos:]``, with
        ``query[query_pos]`` pinned at ``index``."""
        here = placement_score(index)
        if query_pos == len(lowered_query) - 1:
            return here, (index,)

        best: tuple[int, tuple[int, ...]] | None = None
        next_char = lowered_query[query_pos + 1]
        candidate = lowered_text.find(next_char, index + 1)
        while candidate != -1:
            tail = best_from(query_pos + 1, candidate)
            if tail is not None:
                score = tail[0] + (_CONTIGUOUS_BONUS if candidate == index + 1 else 0)
                if best is None or score > best[0]:
                    best = (score, tail[1])
            candidate = lowered_text.find(next_char, candidate + 1)

        if best is None:
            return None
        return here + best[0], (index, *best[1])

    overall: tuple[int, tuple[int, ...]] | None = None
    start = lowered_text.find(lowered_query[0])
    while start != -1:
        result = best_from(0, start)
        if result is not None and (overall is None or result[0] > overall[0]):
            overall = result
        start = lowered_text.find(lowered_query[0], start + 1)

    best_from.cache_clear()

    if overall is None:
        return None

    # Prefer tighter matches: a query that consumes most of the text beats one
    # buried in a long name.
    tail_penalty = (len(lowered_text) - len(lowered_query)) * _UNMATCHED_TAIL_PENALTY
    return Match(score=overall[0] - tail_penalty, indices=overall[1])

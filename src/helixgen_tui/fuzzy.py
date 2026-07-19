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
_GAP_PENALTY = 2
# Deliberately small next to the bonuses above: a start penalty on their scale
# cancels them out, so "rh" would rank the scattered "Rich Harmony" over the
# word-boundary hit in "Crunch Rhythm" — the exact case this module exists for.
# It breaks near-ties toward earlier matches; it does not outweigh a real hit.
_MAX_POSITION_PENALTY = 3


def _lower(text: str) -> str:
    """Lowercase without changing length.

    ``str.lower()`` is not length-preserving (``'İ'.lower()`` is two chars), and
    ``Match.indices`` are offsets into the *original* text. Folding per character
    and keeping only the first result keeps the mapping 1:1."""
    return "".join(char.lower()[0] for char in text)


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

    lowered_query = _lower(query)
    lowered_text = _lower(text)

    def placement_score(index: int) -> int:
        """Score of matching a character at ``index``, ignoring its predecessor."""
        if index == 0:
            return _PREFIX_BONUS
        if lowered_text[index - 1] in _SEPARATORS:
            return _BOUNDARY_BONUS
        return 0

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
                gap = candidate - index
                # Adjacent characters earn the contiguity bonus; anything looser
                # pays for every character it skipped, so a scattered match never
                # outranks a real substring hit.
                adjustment = _CONTIGUOUS_BONUS if gap == 1 else -(gap - 1) * _GAP_PENALTY
                score = tail[0] + adjustment
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
        if result is not None:
            # The position penalty is charged once, on where the match begins —
            # not per matched character, which would scale it by query length and
            # bury late substring hits under scattered early ones.
            scored = (result[0] - min(start, _MAX_POSITION_PENALTY), result[1])
            if overall is None or scored[0] > overall[0]:
                overall = scored
        start = lowered_text.find(lowered_query[0], start + 1)

    if overall is None:
        return None

    # Prefer tighter matches: a query that consumes most of the text beats one
    # buried in a long name.
    tail_penalty = len(lowered_text) - len(lowered_query)
    return Match(score=overall[0] - tail_penalty, indices=overall[1])

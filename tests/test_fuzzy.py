"""Unit tests for the scored fuzzy matcher.

Assertions are about ordering properties and behavior, never absolute score
numbers — the weights are an implementation detail.
"""

from helixgen_tui.fuzzy import Match, match


def test_empty_query_matches_everything_with_zero_score():
    result = match("", "JCM800 Crunch")
    assert result == Match(score=0, indices=())


def test_non_subsequence_returns_none():
    assert match("zzz", "JCM800 Crunch") is None


def test_gappy_subsequence_matches():
    assert match("jcm", "Jazz Chorus Mod") is not None


def test_case_insensitive():
    assert match("JCM", "jcm800 crunch") is not None
    assert match("jcm", "JCM800 Crunch") is not None


def test_contiguous_outranks_gappy():
    contiguous = match("jcm", "JCM800 Crunch")
    gappy = match("jcm", "Jazz Chorus Mod")
    assert contiguous is not None and gappy is not None
    assert contiguous.score > gappy.score


def test_prefix_outranks_mid_string():
    prefix = match("cru", "Crunch Rhythm")
    mid = match("cru", "JCM800 Crunch")
    assert prefix is not None and mid is not None
    assert prefix.score > mid.score


def test_word_boundary_outranks_mid_token():
    boundary = match("rh", "Crunch Rhythm")
    mid = match("rh", "Crunchrhythm")
    assert boundary is not None and mid is not None
    assert boundary.score > mid.score


def test_indices_point_at_the_matched_characters():
    result = match("jcm", "JCM800 Crunch")
    assert result is not None
    assert "".join("JCM800 Crunch"[i] for i in result.indices).lower() == "jcm"


def test_indices_are_strictly_increasing():
    result = match("cnh", "Crunch Rhythm")
    assert result is not None
    assert list(result.indices) == sorted(set(result.indices))


def test_unicode_is_safe():
    result = match("ee", "Crème Brûlée")
    assert result is None or "".join("Crème Brûlée"[i] for i in result.indices).lower() == "ee"


def test_full_string_match_scores_highest_of_its_query():
    exact = match("crunch", "Crunch")
    embedded = match("crunch", "JCM800 Crunch Lead")
    assert exact is not None and embedded is not None
    assert exact.score > embedded.score

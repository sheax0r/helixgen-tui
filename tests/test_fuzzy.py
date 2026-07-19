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
    """A no-match would silently satisfy an `is None or ...` assertion, so pin
    the actual hit: this test exists to catch non-ASCII text breaking indices."""
    result = match("ee", "Crème Brûlée")
    assert result is not None
    assert result.indices == (4, 11)
    assert "".join("Crème Brûlée"[i] for i in result.indices).lower() == "ee"


def test_non_ascii_query_matches_non_ascii_text():
    result = match("brûlée", "Crème Brûlée")
    assert result is not None
    assert "".join("Crème Brûlée"[i] for i in result.indices) == "Brûlée"


def test_full_string_match_scores_highest_of_its_query():
    exact = match("crunch", "Crunch")
    embedded = match("crunch", "JCM800 Crunch Lead")
    assert exact is not None and embedded is not None
    assert exact.score > embedded.score


def test_substring_hit_outranks_scattered_earlier_match():
    """Ranking regression: the position penalty is charged once, on where the
    match starts — not per matched character, which scaled it by query length
    and buried real substring hits under scattered initials."""
    substring = match("amp", "Vintage Guitar Amp")
    scattered = match("amp", "A Massive Powerful Thing")
    assert substring is not None and scattered is not None
    assert substring.score > scattered.score


def test_contiguous_late_match_outranks_gappy_early_one():
    tight = match("crunch", "Zebra Crunch")
    spread = match("crunch", "C R U N C H aaaa")
    assert tight is not None and spread is not None
    assert tight.score > spread.score


def test_shorter_name_wins_when_placement_is_identical():
    """Isolates the unmatched-tail penalty: both are prefix matches at index 0,
    so only the trailing length separates them."""
    exact = match("crunch", "Crunch")
    padded = match("crunch", "Crunchy Rhythm Tone")
    assert exact is not None and padded is not None
    assert exact.score > padded.score


def test_position_penalty_is_clamped_far_into_a_long_name():
    """Past the clamp, placement quality still decides — a boundary hit at a
    very late index beats a mid-token one that starts earlier."""
    boundary = match("cab", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa Cab")
    mid_token = match("cab", "aaaaaaaaaaaaaaaaaaaaaaaaaCabxxxxxx")
    assert boundary is not None and mid_token is not None
    assert boundary.score > mid_token.score


def test_indices_align_with_original_text_when_lowercasing_grows():
    """`'İ'.lower()` is two characters; indices must stay offsets into the
    original string or highlights land on the wrong characters."""
    result = match("cab", "İstanbul Cab")
    assert result is not None
    assert result.indices == (9, 10, 11)
    assert "".join("İstanbul Cab"[i] for i in result.indices) == "Cab"

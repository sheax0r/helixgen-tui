# Plan: Fuzzy search everywhere

## Context

Implements `docs/BACKLOG.md #10 "Fuzzy search everywhere"`. Design spec:
`docs/superpowers/specs/2026-07-19-fuzzy-search-everywhere-design.md` (read it
first — this plan is self-contained, but the spec records the decisions and why).

Today only the Library screen has a filter (`/`), and it is a **boolean**
name-subsequence match (`_subsequence_match` in `src/helixgen_tui/screens/library.py`).
Every other list surface has no filter at all. This change:

1. adds a **scored/ranked** fuzzy matcher in a new pure module `src/helixgen_tui/fuzzy.py`,
2. adds a shared `FilterableTableMixin` that wires a filter `Input` to a `DataTable`
   (filter → rank best-first → highlight matched chars → preserve cursor),
3. rolls it out to every list surface: Library, Setlists left pane, `AddToneModal`,
   and the two IR panes.

Repo rules that apply throughout: **TDD** — failing test first, Textual pilot for
screen logic, fake services from `tests/fake_core.py` / `tests/conftest.py`. The TUI
stays a view/controller over the `helixgen` package — no `.hsp` parsing, no protocol
logic, no engine changes here. **Device writes are explicit user actions, never a
navigation side effect** — this is why Enter-to-act deliberately does NOT trigger
activate/sync/push/delete (see Task 2 and Task 5).

### Settled decisions (do not re-litigate)

- **Scored + ranked**, not boolean. When a query is active the list re-sorts
  best-first; with an empty query the native order is preserved exactly.
- **Enter commits the surface's primary action** on the top-ranked hit — EXCEPT
  where that action mutates the device. Per surface: Library = move cursor only;
  Setlists = move cursor; `AddToneModal` = dismiss with the top hit (adds it);
  IR panes = focus the top hit only.
- **IR screen gets ONE filter**, targeting whichever pane has focus (not one per pane).
- **Write our own matcher.** Textual ships `textual/fuzzy.py`; we do not use it.
  A pure, dependency-free module gives a stable, unit-testable API and decouples us
  from Textual internals.
- **Retire the positional row-key scheme.** The IR panes key rows by `str(index)` into
  the backing list (`self._local_irs[int(row_key.value)]`) because IR display names
  routinely duplicate and `DataTable` rejects duplicate keys. Filtering rows breaks
  that index math. The mixin keeps an ordered `_visible` list mirroring displayed rows,
  and `selected()` returns `_visible[cursor_row]`.

### Out of scope — file as backlog entries, not TODO comments

- Multi-field matching (guitar / description / pack / hash). Match the surface's
  primary name text only.
- `BlockPickerModal` (tone editor category→model picker). The mixin will fit it later.
- Trigram matching. Ordered-subsequence + scoring covers "type part of a name".

---

### Task 1: Scored fuzzy matcher (`src/helixgen_tui/fuzzy.py`)

Pure module. No Textual import, no Rich import. Unit-tested in isolation.

- [x] Write the failing tests first in a new `tests/test_fuzzy.py` (top-level peer of
      `tests/test_shell.py`). Assert **ordering properties and behavior, never absolute
      score numbers** — the weights are an implementation detail and hard-coding them
      makes the tests brittle. Cover:

```python
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
```

- [x] Run it to confirm it fails for the expected reason:
      `uv run pytest tests/test_fuzzy.py -v` → `ModuleNotFoundError: No module named 'helixgen_tui.fuzzy'`
- [x] Implement the minimal module. Shape below. **Deviation:** the greedy
      left-to-right walk sketched here cannot satisfy
      `test_word_boundary_outranks_mid_token` — greedy alignment picks the same
      indices `(1, 5)` for both "Crunch Rhythm" and "Crunchrhythm", so no
      weighting can separate them. Shipped version keeps the same public API
      (`Match`, `match`) and weights, but searches for the best-scoring
      alignment via a memoised recursion instead of the first one.

```python
"""Scored fuzzy matching for list filtering.

Pure — no Textual, no Rich. The ordered-subsequence gate is a strict superset
of a contiguous-substring match, so anything that matched the old boolean
filter still matches here. Scores are only meaningful when comparing results
of the *same* query; never compare scores across different queries.
"""

from __future__ import annotations

from dataclasses import dataclass

_SEPARATORS = " -_/.()[]"

# Relative weights. Tuned for "type part of a name"; tests assert ordering, not values.
_CONTIGUOUS_BONUS = 8
_BOUNDARY_BONUS = 6
_PREFIX_BONUS = 10
_POSITION_PENALTY = 1
_UNMATCHED_TAIL_PENALTY = 1


@dataclass(frozen=True)
class Match:
    """A successful match. ``score`` ranks results of one query (higher = better);
    ``indices`` are the positions in the original text of the matched characters,
    strictly increasing, for highlighting."""

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

    indices: list[int] = []
    score = 0
    text_pos = 0
    previous_index: int | None = None

    for char in lowered_query:
        found = lowered_text.find(char, text_pos)
        if found == -1:
            return None

        if found == 0:
            score += _PREFIX_BONUS
        if previous_index is not None and found == previous_index + 1:
            score += _CONTIGUOUS_BONUS
        if found > 0 and lowered_text[found - 1] in _SEPARATORS:
            score += _BOUNDARY_BONUS

        score -= min(found, 20) * _POSITION_PENALTY

        indices.append(found)
        previous_index = found
        text_pos = found + 1

    # Prefer tighter matches: a query that consumes most of the text beats one
    # buried in a long name.
    score -= (len(lowered_text) - len(lowered_query)) * _UNMATCHED_TAIL_PENALTY

    return Match(score=score, indices=tuple(indices))
```

- [x] Run the tests and confirm they pass: `uv run pytest tests/test_fuzzy.py -v`.
      If a specific ordering test fails, adjust the **weights** (not the test) until
      all ordering properties hold together — that's the point of asserting order.
- [x] Run `uv run ruff check .` and confirm clean.
- [x] Commit: `feat: add scored fuzzy matcher (#10)`

### Task 2: `FilterableTableMixin` + adopt it on the Library screen

Build the shared mixin and prove it on the one surface that already has a filter.
This retires `_subsequence_match` and converts Library to ranked + highlighted.

**Why a mixin and not a base-class method:** the four target surfaces span two
hierarchies — `LibrarianScreen` subclasses (`library.py`, `setlists.py`, `irs.py`)
and Textual `ModalScreen` subclasses (`AddToneModal`). A method on
`LibrarianScreen` could never reach the modal.

Put the mixin in `src/helixgen_tui/screens/filterable.py` (a focused new module —
`screens/base.py` already carries the shared cursor helpers and shouldn't grow a
second concern).

- [ ] Write the failing tests first. Extend `tests/screens/test_library.py` using the
      established Textual pilot + fake-service pattern already in that file. Cover:

```python
async def test_filter_ranks_best_match_first():
    """With a query active, the best match is row 0 even if it is later in
    native library order."""
    # library fixture must contain a tone whose gappy match ("Jazz Chorus Mod")
    # sorts BEFORE a contiguous match ("JCM800 Crunch") in native order.
    # After typing "jcm" into #library-filter, row 0 must be JCM800 Crunch.


async def test_empty_filter_restores_native_order():
    """Clearing the filter restores the library's own ordering, unsorted."""


async def test_filter_highlights_matched_characters():
    """The Tone cell for a filtered row is a rich Text whose matched character
    positions carry the highlight style."""


async def test_enter_on_filter_moves_cursor_to_top_hit_without_activating():
    """Enter in the filter input moves the table cursor to the top hit and does
    NOT call the device service (no activate, no sync)."""
    # assert the fake DeviceService recorded zero calls.


async def test_gappy_subsequence_still_narrows():
    """Regression guard for the existing behavior: the old boolean subsequence
    test must keep passing under the scored matcher."""
```

- [ ] Run them to confirm they fail for the expected reason:
      `uv run pytest tests/screens/test_library.py -v`
- [ ] Implement `src/helixgen_tui/screens/filterable.py`. Required surface:

```python
"""Shared filter/rank/highlight wiring for a filter Input over a DataTable.

A mixin, not a base class: it serves both LibrarianScreen subclasses and
ModalScreen modals, which share no common ancestor of ours.

The mixin owns ``_visible`` — the ordered list of items currently displayed,
mirroring the table's rows 1:1. Hosts resolve the selected item through
``selected()``, never by parsing row keys. This is what lets the IR panes
filter safely despite duplicate display names.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from rich.text import Text
from textual.widgets import DataTable, Input

from helixgen_tui.fuzzy import match

HIGHLIGHT_STYLE = "bold"


class FilterableTableMixin:
    """Wire a filter ``Input`` to a ``DataTable`` with scored fuzzy filtering.

    Hosts must provide:
      - ``filter_input_id`` / ``filter_table_id``
      - ``filter_items() -> Sequence[Any]``      backing source list, native order
      - ``filter_text(item) -> str``             primary text to match + highlight
      - ``filter_row(item, label: Text) -> tuple[Any, ...]``  cells for the row,
        given the pre-highlighted primary label
      - ``filter_row_key(item) -> str | None``   stable key, or None for no key
      - ``filter_on_enter(item) -> None``        primary action on the top hit
    """

    _visible: list[Any]

    def rebuild_filtered(self) -> None:
        """Filter, rank, highlight, rebuild the table, preserve the cursor."""
        table = self.query_one(f"#{self.filter_table_id}", DataTable)
        previous_key = self._capture_cursor_key(table)
        query = self.query_one(f"#{self.filter_input_id}", Input).value.strip()

        scored: list[tuple[int, int, Any, tuple[int, ...]]] = []
        for position, item in enumerate(self.filter_items()):
            result = match(query, self.filter_text(item))
            if result is None:
                continue
            scored.append((result.score, position, item, result.indices))

        if query:
            # -score for best-first; position keeps native order stable within a tie.
            scored.sort(key=lambda row: (-row[0], row[1]))

        table.clear()
        self._visible = []
        for _score, _position, item, indices in scored:
            label = Text(self.filter_text(item))
            if query:
                for index in indices:
                    label.stylize(HIGHLIGHT_STYLE, index, index + 1)
            key = self.filter_row_key(item)
            table.add_row(*self.filter_row(item, label), key=key)
            self._visible.append(item)

        self._restore_cursor_key(table, previous_key)

    def selected(self) -> Any | None:
        """The item under the cursor, resolved through the visible list."""
        table = self.query_one(f"#{self.filter_table_id}", DataTable)
        row = table.cursor_row
        if row is None or not (0 <= row < len(self._visible)):
            return None
        return self._visible[row]

    def handle_filter_submitted(self) -> None:
        """Enter in the filter input: act on the top-ranked hit, if any."""
        if not self._visible:
            return
        self.filter_on_enter(self._visible[0])
```

  Notes for the implementer:
  - `_capture_cursor_key` / `_restore_cursor_key` are existing static helpers on
    `LibrarianScreen` in `src/helixgen_tui/screens/base.py`. `AddToneModal` is not a
    `LibrarianScreen`; give the mixin a safe fallback (e.g. `getattr`-guarded, or lift
    those two statics into the mixin and have `base.py` keep delegating) rather than
    duplicating the logic. Pick one and apply it consistently.
  - Hosts hook `Input.Changed` → `rebuild_filtered()` and `Input.Submitted` →
    `handle_filter_submitted()`.

- [ ] Rewire `src/helixgen_tui/screens/library.py`:
  - Delete `_subsequence_match` (L35-43) entirely — the matcher now lives in `fuzzy.py`.
  - Make `LibraryScreen` inherit the mixin alongside `LibrarianScreen`.
  - Replace the `_rebuild_table` filter loop with `rebuild_filtered()`, supplying
    `filter_text = lambda tone: tone.name`, `filter_row_key = lambda tone: tone.tone_id`,
    and `filter_row` returning `(label, Text(tone.guitar or ""), _SYNC_GLYPH[tone.sync])`.
  - `filter_on_enter(tone)` moves the table cursor to that tone's row. It must **not**
    call `action_make_active` or `action_sync_tone` — those stay on `a` / `s`.
  - Keep the `/` focus and `escape` clear bindings exactly as they are.
- [ ] Run the tests and confirm they pass:
      `uv run pytest tests/test_fuzzy.py tests/screens/test_library.py -v`
- [ ] Run the full suite — this task touches shared code:
      `uv run pytest` and `uv run ruff check .`
- [ ] Commit: `feat: add FilterableTableMixin, rank + highlight library filter (#10)`

### Task 3: Setlists left pane filter

- [ ] Write the failing tests first in `tests/screens/test_setlists.py`:

```python
async def test_setlist_filter_narrows_and_ranks():
    """Typing into the setlists filter narrows the left pane and puts the best
    match at row 0."""


async def test_setlist_filter_empty_restores_all():
    """Clearing the filter shows every setlist in native order."""


async def test_enter_on_setlist_filter_moves_cursor_to_top_hit():
    """Enter moves the left-pane cursor to the top hit; the right-hand tones
    pane rebuilds for that setlist (RowHighlighted fires as usual)."""


async def test_setlist_filter_does_not_break_tones_pane():
    """With a filter active, the tones pane still shows the tones of the
    cursored setlist, not of a stale index."""
```

- [ ] Run to confirm they fail: `uv run pytest tests/screens/test_setlists.py -v`
- [ ] Implement in `src/helixgen_tui/screens/setlists.py`:
  - Add an `Input` with id `setlists-filter` above the `setlists-table` `DataTable`
    (id `setlists-table`, L149). Mirror Library's placeholder/CSS treatment.
  - Add `Binding("slash", "focus_filter", "Filter", key_display="/")` and
    `Binding("escape", "clear_filter", "Clear", show=False)` to the screen's BINDINGS
    (currently L125-133) — same keys and behavior as Library, for consistency.
  - Mix in `FilterableTableMixin` with `filter_text = lambda setlist: setlist.name`,
    `filter_row_key = lambda setlist: setlist.name`.
  - `filter_on_enter(setlist)` moves the cursor to that setlist's row (which makes
    `RowHighlighted` fire and rebuild the tones pane). No sync, no mutation.
  - Route `_selected_setlist()` (L208-217) through the mixin's `selected()` so a
    filtered pane resolves correctly.
- [ ] Run the tests and confirm they pass: `uv run pytest tests/screens/test_setlists.py -v`
- [ ] Commit: `feat: fuzzy filter on the setlists pane (#10)`

### Task 4: `AddToneModal` filter + enter-to-add

`AddToneModal` is a `ModalScreen[str | None]` nested in
`src/helixgen_tui/screens/setlists.py` (L40-87). It lists candidate tones in a
single-column `DataTable` and confirms via `DataTable.RowSelected` →
`dismiss(event.row_key.value)`.

- [ ] Write the failing tests first in `tests/screens/test_setlists.py` (that file
      already exercises `AddToneModal`):

```python
async def test_add_tone_modal_filter_narrows_and_ranks():
    """Typing in the modal filter narrows the candidate list, best match first."""


async def test_add_tone_modal_enter_adds_top_hit():
    """Type a query, press Enter in the filter: the modal dismisses with the
    top-ranked tone's id and that tone is added to the setlist."""


async def test_add_tone_modal_row_selected_still_works():
    """Arrow to a specific row and press Enter on the table: still dismisses
    with THAT row's tone id, not the top hit."""


async def test_add_tone_modal_escape_still_cancels():
    """Escape dismisses with None; adding nothing."""


async def test_add_tone_modal_filter_is_focused_on_mount():
    """The filter input has focus when the modal opens, so the user can type
    immediately."""
```

- [ ] Run to confirm they fail: `uv run pytest tests/screens/test_setlists.py -v`
- [ ] Implement:
  - Add an always-visible `Input` (id `add-tone-filter`) above the modal's `DataTable`,
    focused on mount. Extend the modal's `DEFAULT_CSS` to lay it out.
  - Mix in `FilterableTableMixin` with `filter_text = lambda tone: tone.name`,
    `filter_row_key = lambda tone: tone.tone_id`, single-column
    `filter_row = lambda tone, label: (label,)`.
  - `filter_on_enter(tone)` → `self.dismiss(tone.tone_id)`.
  - Keep the existing `RowSelected` handler (L83-84) — mouse and arrow-then-Enter on a
    specific row must keep working and must dismiss with *that* row, not the top hit.
  - `escape` behavior: if the filter has text, clear it; if already empty, cancel the
    modal (`dismiss(None)`) as today (L65, L86-87).
- [ ] Run the tests and confirm they pass: `uv run pytest tests/screens/test_setlists.py -v`
- [ ] Commit: `feat: fuzzy filter + enter-to-add in the add-tone modal (#10)`

### Task 5: IR panes — one filter on the focused pane, retire positional row keys

`src/helixgen_tui/screens/irs.py` has two `DataTable`s: local (id `irs-local-table`,
L111) and device (id `irs-device-table`, L114). Both currently key rows by
`str(index)` into the backing list (L143, L207) because IR display names duplicate
(mic/distance variants) and `DataTable` rejects duplicate keys;
`_selected_local_ir` / `_selected_device_ir` (L165, L218) then do
`self._local_irs[int(row_key.value)]`.

**This is the task that most needs the `_visible` list** — filtering rows makes those
stored indices point at the wrong IR. Note the existing rename `Input` (id
`irs-rename-input`, L116, hidden by default L124) is NOT the filter; do not reuse it.

- [ ] Write the failing tests first in `tests/screens/test_irs.py`:

```python
async def test_ir_filter_narrows_the_focused_pane_only():
    """With the local table focused, typing filters the local pane and leaves
    the device pane untouched; focus the device table and it filters that one."""


async def test_ir_filter_ranks_best_match_first():
    """Best match lands at row 0 of the filtered pane."""


async def test_filtered_ir_selection_resolves_to_the_right_ir():
    """REGRESSION GUARD for the positional row-key hazard. Given a backing list
    where the match is NOT at index 0, filter down to it and confirm the
    selected IR is that IR — not whatever sits at the old index."""


async def test_duplicate_display_names_still_select_distinctly():
    """Two IRs sharing a display name but differing by hash: filtering to both
    and moving the cursor selects each distinctly."""


async def test_enter_on_ir_filter_focuses_top_hit_without_mutating():
    """Enter focuses the top hit. It must NOT push, delete, rename, or prune —
    the fake device service records zero mutating calls."""


async def test_ir_filter_clears_on_escape():
    """Escape clears a non-empty filter and restores the full pane."""
```

- [ ] Run to confirm they fail: `uv run pytest tests/screens/test_irs.py -v`
- [ ] Implement:
  - Add a single `Input` (id `irs-filter`), placed above the two panes. `/` focuses it
    (`Binding("slash", "focus_filter", "Filter", key_display="/")`); `escape` clears it.
    Note `escape` is already bound to `cancel_rename` (L99) — the handler must clear the
    filter when the filter has text, and otherwise fall through to the existing
    rename-cancel behavior. Do not regress rename cancellation.
  - The filter applies to whichever pane holds focus. Track the focused pane and rebuild
    that pane on `Input.Changed`; when focus moves between panes, re-apply the current
    query to the newly focused pane and restore the other pane to unfiltered.
  - Use `FilterableTableMixin` for both panes with `filter_text = lambda ir: ir.name`.
    Because the mixin is written for one table per host, either instantiate a small
    per-pane helper object or parameterize `filter_table_id` per rebuild — pick one and
    keep it explicit; do not copy-paste the rebuild logic twice.
  - **Replace** `int(row_key.value)` lookups in `_selected_local_ir` / `_selected_device_ir`
    with resolution through the pane's `_visible` list. Row keys may stay positional for
    `DataTable`'s own uniqueness needs, but nothing may compute a backing index from them.
  - `filter_on_enter(ir)` moves the cursor to that IR only. `p` / `d` / `R` / `P` stay
    explicit keys — Enter must never mutate local or device state.
- [ ] Run the tests and confirm they pass: `uv run pytest tests/screens/test_irs.py -v`
- [ ] Run the full suite: `uv run pytest`
- [ ] Commit: `feat: fuzzy filter on the IR panes, drop positional index lookups (#10)`

### Task 6: User-facing surfaces + backlog bookkeeping

- [ ] Update `src/helixgen_tui/widgets/help_overlay.py`. It currently says
      `/  Fuzzy-filter by name` (L28) under Library only. Make the `/` filter hint
      apply to every screen that now has one (Library, Setlists, IRs) and mention that
      Enter jumps to / acts on the best match. Keep the wording terse and consistent
      with the surrounding entries.
- [ ] Update `README.md` key/tab tables so `/` is listed for the Setlists and IRs
      screens, and the add-tone modal's filter is mentioned.
- [ ] Verify the key-hints footer (`src/helixgen_tui/widgets/status_footer.py`) shows
      the new `/` binding on Setlists and IRs — the bindings added in Tasks 3 and 5
      should surface automatically; if not, wire them.
- [ ] Update `docs/BACKLOG.md`:
  - Mark **#10** resolved: all four surfaces filtered, scored ranking, matched-character
    highlighting, enter-to-act. Note the date (2026-07-19) and this plan.
  - Update **#8(d)** — it says "the library filter matches name only ... the pickers/panes
    have no filter — see #10". The pickers/panes now have filters; name-only remains true.
  - Add new numbered entries for the deferred work: (a) multi-field fuzzy match
    (guitar / description / pack), (b) `BlockPickerModal` fuzzy filter — reuse
    `FilterableTableMixin`, (c) optional shared `ModalScreen` base, since `AddToneModal`
    and `BlockPickerModal` carry near-identical `DEFAULT_CSS`.
- [ ] Run the full validation set (below) and confirm green.
- [ ] Commit: `docs: record fuzzy-search rollout, close #10, file follow-ups`

## Validation Commands

Run from the repo root:

- `uv run pytest` — full offline test suite (Textual pilot screen tests use fake
  services; no device required). Must be green.
- `uv run ruff check .` — lint. Must be clean.
- Targeted, while iterating:
  `uv run pytest tests/test_fuzzy.py tests/screens/test_library.py tests/screens/test_setlists.py tests/screens/test_irs.py -v`

No live-device testing is required for this change: every surface touched is a
local read/filter path, and the whole point of the Enter-to-act design is that no
new code path mutates the device.

# Fuzzy search everywhere — design

**Date:** 2026-07-19
**Backlog:** #10 "Fuzzy search everywhere" (helixgen-tui `docs/BACKLOG.md`; workspace `BACKLOG.md` #10 residual)
**Status:** shipped 2026-07-19 (branch `fuzzy-search-everywhere`)

> Deviations from this design as written are noted inline below; the shipped
> matcher is `src/helixgen_tui/fuzzy.py` and its module docstring is
> authoritative where the two disagree.

## Goal

Type part of a name to find/use the thing, wherever a list is presented. Today
only the Library screen has a filter (`/`), upgraded 2026-07-18 to a boolean
name-subsequence match. Every other list surface has no filter. This makes fuzzy
filtering uniform across all list surfaces, with **scored ranking** (best match
floats to the top), **matched-character highlighting**, and **enter-to-act on
the top hit**.

## Decisions (settled during brainstorming)

1. **Scored + ranked matcher**, not boolean. Enter-to-act on the top hit is only
   meaningful if the best match ranks first. Lists re-sort best-first while a
   query is active; native order returns when the query is empty.
2. **Enter commits the surface's primary action** on the top-ranked hit —
   except the Library screen, whose actions (`a` activate, `s` sync) are
   device-mutating, so there Enter only moves the cursor to the top hit.
3. **IR screen: one filter, focused pane.** A single `/` filters whichever of
   the two IR panes (local / device) currently has focus.
4. **Own matcher module**, not Textual's `textual/fuzzy.py`. A pure,
   dependency-free module gives a stable, unit-testable API and decouples us
   from Textual internals. (Textual's matcher exists and is noted, but not used.)
5. **Unify selection via an ordered visible list**, retiring the fragile
   positional `str(index)` row-key scheme in the IR panes.

## Non-goals (deferred → backlog)

- **Multi-field match.** Match the surface's primary text only (tone/setlist/IR
  name). Matching guitar, description, pack, hash, etc. is deferred.
- **`BlockPickerModal`.** Not listed in #10 (category→model picker in the tone
  editor). Deferred as an optional follow-up; the same mixin will fit it later.
- **Trigram matching.** #10 mentioned trigram as an option; ordered-subsequence
  plus scoring covers "type part of a name" without it.

## Surfaces

All four are `DataTable`-backed. Only Library has a filter today.

| Surface | File (current) | Widget | Filter today | Select/confirm today | Row key today |
|---|---|---|---|---|---|
| Library tone list | `screens/library.py` | `DataTable` id `library-table` | `/` Input `library-filter`, boolean subsequence | `a`/`s` on cursor row | `tone.tone_id` |
| Setlists left pane | `screens/setlists.py` | `DataTable` id `setlists-table` | none | cursor move (`RowHighlighted`) | `setlist.name` |
| Add-tone modal | `AddToneModal` in `screens/setlists.py` | `DataTable` | none | `RowSelected` → `dismiss(tone_id)` | `tone.tone_id` |
| IR local pane | `screens/irs.py` | `DataTable` id `irs-local-table` | none | `p` push on cursor | `str(index)` |
| IR device pane | `screens/irs.py` | `DataTable` id `irs-device-table` | none | `d`/`R` on cursor | `str(index)` |

The IR panes key rows by `str(index)` on purpose: IR display names routinely
duplicate (mic/distance variants) and `DataTable` rejects duplicate keys.
`_selected_local_ir` / `_selected_device_ir` resolve via
`self._local_irs[int(row_key.value)]`. A filter that drops rows breaks that
index math — see the mixin's `_visible` list, which fixes it.

## Component 1 — `src/helixgen_tui/fuzzy.py` (matcher)

Pure module, no Textual import. Unit-tested in isolation.

```python
@dataclass(frozen=True)
class Match:
    score: int            # higher = better; only meaningful vs other matches of same query
    indices: tuple[int, ...]  # positions in text of matched query chars (for highlight)

def match(query: str, text: str) -> Match | None:
    """Case-insensitive ordered-subsequence match with relevance scoring.
    Returns None if query is not a subsequence of text.
    Empty query returns Match(0, ()) — matches everything, native order kept.
    """
```

- **Gate:** ordered case-insensitive subsequence (every query char appears in
  order, gaps allowed). A strict superset of the current boolean matcher — any
  query that matches today still matches.
- **Scoring** (relative, within a single query's result set): reward
  - contiguous runs of matched chars,
  - matches at a word boundary / after a separator (shipped set:
    `` " -_/.()[]" ``),
  - a match at position 0 (prefix),
  - earlier overall position (tie-breaker). *Shipped:* this penalty is
    charged **once**, on the index where the match begins. Charging it per
    matched character scaled it by query length and buried real substring
    hits under scattered early ones. Gaps between matched characters are
    penalized separately, which is what keeps a scattered match from
    outranking a contiguous one.
  Exact weights are an implementation detail; tests assert *ordering* properties,
  not absolute numbers (see Testing).
- **`indices`** returns the chosen matched positions so a caller can bold them.
  When multiple subsequences exist, pick the one the scorer selects; the same
  positions used for scoring are the positions highlighted. *Shipped:* the
  matcher runs a memoised search for the **best-scoring** alignment, not the
  greedy-leftmost one this design assumed — a greedy walk scores `rh` against
  "Crunch Rhythm" on the `r` of "Crunch" and never sees the boundary hit, so
  the boundary and contiguity bonuses would be unreachable for most real
  names. Indices are offsets into the *original* text: the matcher lowercases
  per character so a codepoint whose `.lower()` grows (`'İ'`) cannot shift
  them.
- **Highlight helper** (may live in `fuzzy.py` or the mixin): given `text`,
  `indices`, and a Rich style, return a `rich.text.Text` with matched chars
  styled. Kept out of the pure core if it would pull in Rich; a thin wrapper is
  fine.

## Component 2 — `FilterableTableMixin`

A mixin (not a base class — must serve both `LibrarianScreen` subclasses and
`ModalScreen` modals) that wires a filter `Input` to a `DataTable` over a
backing list. Lives in `screens/base.py` (peer to the existing
`_capture_cursor_key`/`_restore_cursor_key` helpers) or a small dedicated
module if that keeps `base.py` focused.

Configured per host with:
- the `Input` and `DataTable` (or their ids),
- `items() -> list[T]` — the backing source list,
- `row_text(item) -> str` — the primary text to match/highlight,
- `render_row(item, highlighted_text) -> tuple[cells...]` — build the row cells,
  receiving the pre-highlighted primary `Text`,
- `on_enter(top_item)` — surface's primary action for enter-to-act (optional;
  Library passes a cursor-move-only variant).

Behavior:
- **Rebuild** on `Input.Changed`: run `match(query, row_text(item))` over
  `items()`; drop `None`; when query non-empty, **sort by score desc** (stable,
  so equal scores keep native order) — when empty, keep native order and skip
  highlight; rebuild the table; preserve the cursor via the existing
  `_capture_cursor_key`/`_restore_cursor_key` where a stable key exists.
- **`_visible: list[T]`** — the ordered list of items currently shown, mirroring
  displayed rows 1:1. `selected() -> T | None` returns `_visible[cursor_row]`.
  Surfaces resolve the selected item through this, **not** through row-key
  parsing. This retires the IR `str(index)` scheme and removes its fragility.
- **`/` focuses** the filter (screens); modals autofocus it. **esc** clears the
  filter (screens) or, if already empty, defers to the surface (modal cancel).
- **Enter while the input is focused** → `on_enter(_visible[0])` when the list is
  non-empty; no-op on empty result.

## Per-surface wiring

- **Library** (`screens/library.py`): replace `_subsequence_match` with `fuzzy.match`.
  Rank best-first when query set; native order when empty. Highlight matched
  chars in the Tone column. `on_enter` = move cursor to top hit only (do **not**
  activate/sync). Keep `a`/`s` bindings unchanged.
- **Setlists left pane** (`screens/setlists.py`): add a `/` filter `Input` above
  `setlists-table`. Filter+rank by setlist name; highlight. `on_enter` = move
  cursor to top hit (setlist "selection" is cursor-driven; the right pane
  rebuilds off `RowHighlighted` as today). Reorder/sync verbs unchanged.
- **AddToneModal** (`screens/setlists.py`): add an always-visible filter `Input`,
  autofocused, above its `DataTable`. Filter+rank candidate tones; highlight.
  `on_enter` = `dismiss(top_hit.tone_id)` (adds it). Existing `RowSelected`
  (mouse / arrow-then-enter on a specific row) still works.
- **IR panes** (`screens/irs.py`): add one `/` filter `Input` that targets the
  focused pane (local or device). Filter+rank by IR name; highlight. `on_enter`
  = focus the top hit (leave `p`/`d`/`R`/`P` explicit — no auto-mutation). Both
  panes go through `_visible`/`selected()`, dropping `int(row_key.value)`.

## Interaction consistency

- `/` focuses filter on screens; modals show the filter always (autofocused).
- esc clears a non-empty filter; on empty filter, screens defer (no-op) and
  modals cancel.
- Empty query → full list, native order, no highlight.
- Highlight style: bold (optionally an accent color) on matched chars; single
  consistent style across all surfaces.

## Testing (TDD)

- **`tests/test_fuzzy.py`** (new, top-level): ordering properties, not magic
  numbers — contiguous run outranks gappy; prefix outranks mid-word; word-
  boundary start outranks mid-token; empty query matches all with score 0;
  non-subsequence returns None; case-insensensitivity; `indices` line up with
  the matched chars; Unicode-safe.
- **Per-screen** (`tests/screens/test_library.py`, `test_setlists.py`,
  `test_irs.py`): filter narrows and re-ranks (top row is best match); Enter
  commits the right per-surface action (add tone / cursor move / focus);
  highlight present on matched chars; cursor preserved across rebuild where a
  stable key exists; case-insensitivity; **IR regression guard** — after
  filtering, the selected IR resolves to the correct backing item (proves
  `_visible` fixes the index-key hazard).
- **AddToneModal** test (`test_setlists.py` or `tests/widgets/`): type query →
  Enter → modal dismisses with the top-hit tone id.

## Validation commands

From `helixgen-tui/`:

- `uv run pytest` — full suite green.
- `uv run pytest tests/test_fuzzy.py tests/screens/test_library.py tests/screens/test_setlists.py tests/screens/test_irs.py` — targeted.
- lint/type per repo config (`uv run ruff check .`, `uv run mypy` if configured).

## Backlog follow-ups to record

- Multi-field fuzzy match (guitar / description / pack) — deferred here.
- `BlockPickerModal` fuzzy filter — reuse the mixin.
- Optional: shared `ModalScreen` base (AddToneModal / BlockPickerModal CSS is
  near-identical) — related refactor, not required by #10.

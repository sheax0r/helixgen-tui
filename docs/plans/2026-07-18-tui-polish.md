# Plan: TUI polish — ungated footer/filter/selection niceties

## Context

Three clearly-shippable polish items lifted from `docs/BACKLOG.md` #8, #10,
#11 — the subset with no user/hardware/core dependency and no real product
decision. Everything here is a view/controller change over the existing
`helixgen` package: no `.hsp` parsing, no protocol logic, no engine change,
no device write. TDD throughout (failing Textual pilot test first, then the
minimal change); the fake-core + Pilot pattern is established in
`tests/screens/*` and `tests/test_key_hints.py`.

Deliberately **excluded** from this plan (tracked in the backlog, not
implemented here):

- #7 tab-cycling — `tab`/`shift+tab` collide with in-screen focus traversal
  (Library's filter `Input` <-> table); needs a key-choice decision.
- #7 sortable tone list, `--gc` toggle, device-side setlists pane,
  detail-view variants/telemetry — each is a new interaction or a
  core/device dependency.
- #8(b) device `r` retry needing a second press — production-async ordering
  bug, not reproducible under the synchronous fake spawn.
- #8(c) `format_device_text` substring heuristic — intended behavior
  underspecified.
- #10 fuzzy-search on *new* surfaces (add-tone picker, setlist/IR panes),
  match-highlighting, enter-to-act-on-top-hit — new UI + interaction
  decisions. This plan only upgrades the **existing** Library filter's match
  algorithm.
- #11 narrow-width footer overflow — "compact key-only vs priority ordering"
  is an open design fork.

### Task 1: Preserve the DataTable selection across on-screen-resume rebuilds (#8a)

Dismissing a modal fires `ScreenResume`, whose handler rebuilds the mode
screen's table(s) and drops the cursor back to row 0. The flow is unaffected
(selection is captured before the modal), but the visible cursor jump is
cosmetic noise. Fix: capture the highlighted row key before the rebuild and
restore the cursor to that row afterward, on all three list screens. No
product decision — the correct behavior is "keep the selection."

- [x] Write the failing pilot test(s) first: highlight a non-zero row, drive
      a modal open+dismiss (or call the screen's refresh) and assert the
      cursor is still on the same row key — one per screen:
  - Library: `tests/screens/test_library.py` (see `test_screen_resume_refreshes_library`, line ~414)
  - Setlists: `tests/screens/test_setlists.py` (see `test_screen_resume_refreshes_setlists`, line ~417)
  - IRs: `tests/screens/test_irs.py` (see `test_screen_resume_refreshes_local_pane`, line ~354)
- [x] Run them to confirm they fail because the cursor resets to row 0
- [x] Implement the minimal change — capture-then-restore the cursor row by
      its row key around the `table.clear()` rebuild (fall back to row 0 when
      the previously-selected key is gone after the rebuild):
  - `src/helixgen_tui/screens/library.py` — `_rebuild_table` (line ~87), driven by `refresh_tones`/`on_screen_resume` (lines ~79, ~104)
  - `src/helixgen_tui/screens/setlists.py` — `_rebuild_setlist_table` (line ~170) and `_rebuild_tones_table` (line ~177), driven by `refresh_setlists`/`on_screen_resume` (lines ~155, ~165)
  - `src/helixgen_tui/screens/irs.py` — `refresh_local_irs` (line ~131) and `_apply_device_irs` (line ~191)
- [x] Run the tests and confirm they pass
- [x] No user-facing key/help surface changes (behavior-only polish); README
      and help overlay untouched

### Task 2: Library filter — substring -> subsequence fuzzy matching (#10, narrow slice)

The Library `/` filter matches a contiguous substring of the tone name only
(`src/helixgen_tui/screens/library.py:92`, `query not in tone.name.lower()`).
#10 (user request, 2026-07-18) asks for incremental fuzzy matching and lists
"subsequence or trigram" as the options. **Decision (conventional default):
case-insensitive ordered subsequence match on the tone name** — the standard
fuzzy-finder default and strictly a superset of substring, so it stays
backward-compatible (the existing "everlong" substring test keeps matching).
Scope stays name-only and Library-only; matching extra columns and adding
filters to other surfaces are the excluded #10 product decisions. No
match-highlighting, no change to enter behavior.

- [ ] Write the failing pilot test first in `tests/screens/test_library.py`
      (alongside `test_filter_narrows_rows_by_substring`, line ~136): a gappy
      query (e.g. typing `ffever` or `bib`) narrows to the intended tone,
      which a substring match would miss. Keep/verify the existing substring
      test still passes (subsequence is a superset).
- [ ] Run it to confirm it fails under the current substring filter
- [ ] Implement a small pure `_subsequence_match(query, text) -> bool`
      helper (case-insensitive; empty query matches everything) and use it in
      `_rebuild_table` in place of the `query not in tone.name.lower()` check
      (`src/helixgen_tui/screens/library.py:87-99`). Keep the helper local to
      the screen module (or a tiny `helixgen_tui/fuzzy.py`); no dependency on
      the `helixgen` package.
- [ ] Run the tests and confirm they pass
- [ ] Update the filter's user-facing description if it names "substring":
      README filter/key notes and the `?` help overlay — reword to "fuzzy
      filter" if the old wording is present (`src/helixgen_tui/widgets/help_overlay.py`, `README.md`)

## Validation Commands

Run from the repo root:

- `uv run pytest` — full offline test suite (Textual pilot screen tests use
  fake services; no device required).
- `uv run ruff check .` — lint.

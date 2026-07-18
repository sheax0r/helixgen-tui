# Plan: #12 — console-markup safety sweep (crash-bug class)

## Context

Backlog **#12** (`docs/BACKLOG.md`). Textual renders `str` through Rich markup
by default, and `DataTable`'s cell formatter runs `Text.from_markup` on plain
strings — so a tone/IR/device NAME containing `[...]` renders corrupted, and a
malformed tag like `[/]` raises `MarkupError` and CRASHES the whole screen.
User-/device-controlled names reach several unescaped surfaces.

**Base is v0.3.0 (`788f60e`), which added the signal-flow editor v1 (chain
management) inside `screens/tone_editor.py` — those new surfaces MUST be swept
too, not just the original list.** The fix pattern is already established
in-repo (tone_editor, status_footer, tab_strip); apply it everywhere model data
reaches a renderable. Repo rules: TDD (Textual pilot tests with bracket-bearing
fixtures via `tests/fake_core.py`), ruff-clean.

Fix pattern:
- **DataTable cells** → wrap user/device strings in `rich.text.Text(...)`
  (`markup=False` does NOT work on DataTable; `Text` is required).
- **Static widgets / `.update()` with model data** → construct/update with
  `markup=False` (or pass a `Text`).
- **`border_title` / labels that are always markup-parsed** → `rich.markup.escape(...)`.
- Do NOT alter widgets that already return `Text` intentionally
  (`status_footer.py`, `tab_strip.py`) or change deliberate styling.

### Task 1: audit every model-data render surface (do this FIRST)

- [x] Grep all of `src/helixgen_tui/` for `add_row(`, `Static(`, `.update(`,
      `border_title`, and any `_renderable`/`render()` that interpolates model
      strings (tone/IR/setlist/device names, packs, guitars, lock labels,
      block/param names from the signal-flow editor). Produce the definitive
      surface list — screens (library, setlists, irs, device, tone_editor incl.
      the new chain-management/signal-flow views) AND widgets (confirm_modal,
      help_overlay, any new ones). Note which already use `Text`/`markup=False`.

#### Audit findings — definitive surface list

UNSAFE — DataTable cells (fix in Task 2, wrap in `rich.text.Text`):
- `screens/library.py:93` — `add_row(tone.name, tone.guitar or "", glyph)` — `tone.name`, `tone.guitar` are plain str (glyph is a fixed constant).
- `screens/setlists.py:174` — `add_row(setlist.name, glyph, ...)` — `setlist.name` plain str (also used as `key`, which is fine — keys aren't rendered).
- `screens/setlists.py:185` — `add_row(name, key=tone_id)` — tone `name` plain str (setlist detail list).
- `screens/setlists.py:79` — `add_row(tone.name, ...)` — AddToneModal picker, plain str.
- `screens/irs.py:140` — `add_row(ir.name, ir.pack or "", _short_hash(...))` — local IRs; `ir.name` + `ir.pack` device/user strings (hash is safe hex).
- `screens/irs.py:200` — same, device IRs.

UNSAFE — Static / `.update()` / body (fix in Task 3):
- `widgets/confirm_modal.py:50` — `Static(body)`; `body` interpolates `plan.title` + `plan.lines` (model data) AND the literal `[y] confirm   [n] cancel` footer, which console-markup would eat. Needs `markup=False` (also protects the literal footer).
- `screens/device.py:125` + `:178`/`:180` — `Static("", id=_INFO_ID)` updated with info dict values + `Active tone: {state.active_tone}`. Default `markup=True`; `update()` re-parses. Fix: create `markup=False` (or wrap update text in `Text`).
- `screens/device.py:126` + `:204` — `Static("", id=_LOCKS_ID)` updated with lock labels. Same fix.

ALREADY SAFE (do not touch — pattern already applied):
- `screens/tone_editor.py:193,194` — `Static(..., markup=False)` (header, chain).
- `screens/tone_editor.py:357` — `static.update(text)` where `text` is a `Text`.
- `screens/tone_editor.py:370,376,377,384` — `add_row(Text(...), Text(...))`.
- `screens/tone_editor.py:566` — `border_title = escape(f"edit {param.name}")`.
- `widgets/block_picker_modal.py:57` — `Static(..., markup=False)` title; `:74,:84` — `add_row(Text(...))`.
- `widgets/status_footer.py:42,43`, `widgets/tab_strip.py:31` — intentionally return `Text`.

NOT MODEL DATA (out of scope — no interpolated model strings):
- `screens/tone_editor.py:579` — `border_title = f"edit {label}"`, `label` is fixed `"Level"`/`"Pan"`.
- `widgets/help_overlay.py:91` — `Static(HELP_TEXT)`, static constant with no `[` brackets.
- `screens/device.py:65,174`, `screens/irs.py:109,112,114`, `screens/setlists.py:72` — fixed literal strings, no model interpolation, no brackets.

### Task 2: DataTable cell surfaces

- [x] Failing pilot tests first (mirror the existing
      `tests/screens/test_tone_editor.py` bracket tests), per screen, with
      bracket-bearing fixture names (`"Bad [/] name"`, `"[reverb]"`): assert the
      screen stays alive (no MarkupError) AND the literal brackets appear in the
      cell read back via `str(cell)`.
- [x] Wrap all identified DataTable cell values (library, setlists incl.
      AddToneModal picker, irs local+device, and any signal-flow/chain tables in
      tone_editor) in `rich.text.Text(...)`.

### Task 3: Static / update / border_title surfaces

- [x] Failing tests: ConfirmModal from a bracketed name doesn't crash and shows
      body + the `[y]/[n]` footer LITERALLY; DeviceScreen `#info`/`#locks` with
      bracketed active-tone name / lock label don't crash; any tone_editor
      static/header/border_title with a bracketed block or param name renders
      literally without crash.
- [x] Apply `markup=False` (or `Text`, or `escape()` for border_title) to every
      surface from Task 1 not already safe. Confirm no intended styling is lost.

### Task 4: confirm complete

- [x] Re-run the Task 1 grep; every model-data surface is now `Text` /
      `markup=False` / escaped, or explicitly justified as already-safe. No
      surface left behind (especially in the new signal-flow editor code).

## Validation Commands

- `uv run pytest` — full offline Textual suite (pilot tests, fake services).
- `uv run ruff check .` — lint (line-length 100, E501).

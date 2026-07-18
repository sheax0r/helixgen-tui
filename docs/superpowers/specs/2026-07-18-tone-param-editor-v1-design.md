# Tone param editor v1 — design

Status: shipped as **draft PR** for UX review (v0.2.0). Scope: edit knob/param
values on blocks that already exist in a tone's signal chain, writing back to the
library `.hsp`. Full chain management (add/remove/reorder blocks, splits/parallel
paths) is **out of scope** — deferred to backlog #13. Device is never touched.

## Where it sits

Pressing **Enter** on a tone in the Library screen now opens `ToneEditorScreen`
(previously `ToneDetailModal`, now removed — its name/guitar/setlists/description
metadata is folded into the editor's header pane, so nothing is lost).

## Layout

- **Left pane** — every block in chain order, grouped/labeled by `@path` (the
  parallel lane), showing model display name, `@position`, and enabled/bypassed
  state. Read-only `State` in v1 (bypass toggle is chain management -> backlog).
- **Right pane** — the selected block's params, one row per param: name + current
  value. Params are enumerated from the raw slot params (every param the block
  carries), not from `view.view`.

## Navigation & keys (shown in footer + `?` help)

| Key            | Action                                                         |
|----------------|----------------------------------------------------------------|
| up / down      | move selection in the focused pane                             |
| tab            | switch focus between the blocks pane and the params pane       |
| left / right   | nudge the selected param (params pane only)                    |
| enter          | manual entry: edit the selected param's value, commit w/ enter |
| s / ctrl+s     | save all edits to the library `.hsp`                           |
| escape         | leave the editor (confirms first if there are unsaved edits)   |

Focus model: the two `DataTable`s are made non-focusable (`can_focus=False`) so
every nav key reaches the screen's own bindings; selection cursors are moved
programmatically. Manual entry mounts a focused `Input` (which consumes typing +
enter); nav actions are gated while it is open.

## Adjusting a value

- **float** — left/right nudge by 0.01, clamped to `[0.0, 1.0]`, rounded to 2 dp.
- **int** — nudge by +/-1 (no authoritative range, so no bound clamp).
- **bool** — left/right/manual toggles `True`/`False` (also accepts `0`/`1`).
- **manual entry** — typed value committed with enter; validated for the param's
  type (float/int/bool/str), out-of-range floats clamped to `[0,1]`, bad input
  rejected with an inline error in the status footer; edit stays open.

## Save semantics (explicit, never autosave)

- A **dirty indicator** (`unsaved`) shows in the header the moment a value
  differs from disk, and clears on a successful save. An edit returning a param
  to its on-disk value prunes itself from the dirty set.
- `s` / `ctrl+s` writes back through the adapter. Leaving with unsaved edits
  (`escape`) raises a confirm modal (`Discard unsaved changes?`).
- Save result (success / failure / count) is reported in the status footer.
- Device is untouched — v1 edits the library `.hsp` only.

## Architecture

- **VMs** (`core/models.py`, frozen): `ChainVM(tone_id, name, guitar, description,
  setlists, paths)`, `PathVM(path, blocks)`, `BlockVM(model, display, position,
  path, enabled, params)`, `ParamVM(name, value, type, default)`, plus
  `ParamChange(model, path, position, param, value)` describing one edit.
- **Port** (`core/ports.py`): `EditorPort.get_chain(tone_id) -> ChainVM | None`
  and `save_params(tone_id, changes) -> OpResult`. Added to the `Core` protocol.
- **Adapter** (`core/editor.py`, `RealEditor`): the only new code that imports
  `helixgen`. Reads via `hsp.read_hsp` + `hsp.extract_blocks_from_hsp`, enriches
  param type/default from `library.Library.find_block(...).params` (falls back to
  inferring the type from the current value when a block/param is not catalogued,
  since `find_block` raises for un-ingested blocks). Locates the `.hsp` through
  `SetlistManifest.tone_path(tone_id)` (same source `RealLibrary` uses). Writes
  via `mutate.set_param(body, model, param, value, library, lane=path, pos=pos)` —
  **coordinate mapping discovered empirically**: the raw block's `@path` is the
  parallel *lane*, `@position` is the slot *pos*, and the model id disambiguates;
  the flow index is not exposed by `extract_blocks_from_hsp`, so a save that is
  genuinely ambiguous (same model at same lane+pos in two DSP flows) fails safe
  with a `MutateError` rather than writing the wrong slot. `set_param` does not
  clamp ranges, so the screen clamps floats to `[0,1]` before calling. Writes are
  atomic: any per-change `set_param` failure aborts before `write_hsp`, leaving
  disk untouched.
- **Fake** (`tests/fake_core.py`, `FakeEditorPort`): in-memory `ChainVM` store;
  records every `save_params` call in `.calls` so screen tests assert on it.

## Deferred (backlog)

- **#13** full chain management (add/remove/reorder + splits/parallel paths).
- **#14** param-schema enrichment dependency on core (cross-refs #3).

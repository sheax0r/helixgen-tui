# Signal-Flow Editor (chain management) — Design Spec

- **Date:** 2026-07-18
- **Repo:** helixgen-tui
- **Status:** approved design (user pre-approved spec + plans + merge + release)
- **Implements:** backlog **#13** (full chain management) + two extras the user
  asked for (output pan/volume, input source). Builds on the shipped
  **tone param editor v1** (`2026-07-18-tone-param-editor-v1-design.md`, v0.2.0).

## Origin

User asked for "a mode where you can visually arrange blocks, add new ones,
delete old ones, do path-splits and joins" plus: change the path, see/modify
**output pan & volume**, and choose **input source** (Guitar 1 / Guitar 2 /
both). These map onto existing backlog **#13** (chain management) plus output
and input handling that #13 does not cover.

## What already exists (do NOT rebuild)

`ToneEditorScreen` (v0.2.0, `screens/tone_editor.py`) opens on **Enter** from the
Library. Two panes: left = every block in chain order grouped by `@path` lane;
right = the selected block's params, editable (float nudge / int / bool / manual
entry), saved to the library `.hsp` with an explicit `s`, dirty indicator, and a
confirm-discard modal. Device is never touched. VMs already in `core/models.py`:
`ChainVM(tone_id, name, guitar, description, setlists, paths)`,
`PathVM(path, blocks)`, `BlockVM(model, display, position, path, enabled, params)`,
`ParamVM(name, value, type, default)`, `ParamChange(...)`. Port
`EditorPort.get_chain / save_params` with `RealEditor` adapter (`core/editor.py`)
and `FakeEditorPort` (`tests/fake_core.py`).

**Value-editing on existing blocks is done.** This spec adds *structural* editing
and the output/input surfaces around it.

## Core capabilities today (verified against helixgen 0.26.0)

| Operation | Core support | Where |
|---|---|---|
| Block **add / delete** | yes, **serial paths only** (refused if path has a split/join) | `mutate.add_block` / `mutate.remove_block`; CLI `add-block`/`remove-block`/`patch` |
| Block **swap model** (same category) | yes | `mutate.swap_model` / `swap-model` |
| Block **bypass / enable** | yes | `mutate` bypass verb / `device bypass` (live) |
| **Output** pan & level | yes, full read+write | `mutate.set_flow_param` → `set-param output level|pan`; read via `view` |
| Split/join **params** of an *existing* split (Y balance, route, crossover, mixer A/B level+pan, polarity, master) | yes, read+write | `set-param split|join`; `view` |
| Block **reorder / move** | **none** | — |
| **Insert / delete** a split or join | **none** (author-time only) | — |
| Add/delete block on a **parallel** path | **none** (refused) | — |
| **Change path / lane topology** | **none** (fixed at generate) | — |
| **Input source** (gtr1/2/both) write | **none exposed** (`set_input` exists but is wired only into `generate`) | read via `view`: `_lift_input`/`_input_mode` emit `inst1/inst2/both/none` |
| Multi-flow / dual-slot addressing | not exposed (`extract_blocks_from_hsp` has no flow index) | backlog #13 note |

Structural edits are **local-`.hsp`-only**; there is no live device protocol for
add/remove/reorder/split. Live device verbs are param/bypass/model only.

## Scope

### v1 — this spec, TUI-only (no core change, no device write)

Extend the tone editor into a **signal-flow editor** with a horizontal chain
view and the structural edits core already supports, all writing to the library
`.hsp` exactly as the v0.2.0 editor does (device untouched):

1. **Horizontal chain view.** Render the chain left-to-right (Stadium-like), one
   row per lane, both DSP paths stacked when present, split/join drawn as
   `+`/`-` connectors. This becomes the block-selection surface (replaces the
   plain left list as the primary navigator; the params inspector stays). Chain
   wider than the pane scrolls horizontally.
2. **Add block** (`a`) — model picker (category → model), inserts after the
   cursor. **Serial path only**; on a parallel path, refuse with a clear
   status-footer reason.
3. **Delete block** (`x`) — serial path only, same refusal rule.
4. **Swap model** — same-category swap on the selected block.
5. **Bypass / enable toggle** (`b`) — flips the block's enabled state (backlog
   #13 lists this with the structural work).
6. **Output block** — surfaced as the chain's terminal node; its **pan** and
   **level/volume** are editable in the inspector (core `set-param output`).
7. **Input block** — surfaced as the chain's head node; shows **source**
   (Guitar 1 / Guitar 2 / both), **read-only** in v1 (write needs core, see B).

Save semantics unchanged: explicit `s` writes the `.hsp`; dirty indicator;
confirm-discard on leave. Structural edits fail **atomically** (any per-op
failure aborts before write, disk untouched) — same contract as the value
editor.

### v2 — live propagation (follow-up)

Editing the **currently-active** device tone propagates **param-class** edits
(output pan/vol, block params, bypass, same-cat swap) live via `device set-param`
/ `bypass` / `model`, with a **LIVE** badge and write-gating; structural edits
stay local and carry a **"save to hear"** marker (no live structural protocol
exists). Saved slot updates only on `s`. Deferred to keep v1 device-free.

### Scope-B — core-first fast-follow (each needs a helixgen-core PR)

Engine changes land in core first (cross-repo invariant). New core verbs, then
TUI wiring:

1. Parallel-aware `add-block` / `remove-block` (drop the split/join refusal).
2. `move-block` / reorder.
3. Split / join **insert** and **delete**.
4. Path / lane **topology** edit (move block across paths/lanes; add/remove path).
5. **Input source** edit (expose `set_input` via CLI/patch) → flips v1's
   read-only input to editable.
6. Flow-index-aware block coordinates (fixes multi-flow / dual-slot; backlog #13
   + core #3).

## Non-goals (v1)

Everything in v2 and scope-B. No device writes. No `.hsp` parsing or protocol
logic in the TUI (stays view/controller over `helixgen`).

## Architecture (follows the repo's established pattern)

Reuse the existing editor plumbing; add structural verbs and the new render.

- **Models** (`core/models.py`): the chain VMs exist. Add as needed: a
  `BlockCatalogVM`/category listing for the add-block picker, and extend the
  chain VMs so output pan/level and input source are addressable nodes (e.g. an
  `OutputVM(level, pan)` and `input source` on `ChainVM`), all frozen, `tuple`
  sequences, `str | None` optionals — matching existing conventions.
- **Port** (`core/ports.py`): extend `EditorPort` with structural verbs —
  `add_block(tone_id, after, model) -> OpResult`,
  `remove_block(tone_id, block) -> OpResult`,
  `swap_model(tone_id, block, model) -> OpResult`,
  `set_bypass(tone_id, block, enabled) -> OpResult`,
  `set_output(tone_id, level, pan) -> OpResult`,
  `list_block_catalog() -> tuple[BlockCatalogVM, ...]`. Each returns `OpResult`;
  parallel-path add/remove returns `OpResult(ok=False, ...)` with a clear reason.
- **Adapter** (`core/editor.py`, `RealEditor`): implement the new verbs over
  `helixgen.mutate` (`add_block`/`remove_block`/`swap_model`/bypass) and
  `mutate.set_flow_param` (`output level|pan`), reading the catalog from
  `library.Library`. Same atomic-write discipline as `save_params`
  (validate/build in memory, single `write_hsp`, disk untouched on any failure).
  Reuse the empirically-mapped `(lane=@path, pos=@position, model)` coordinates;
  keep the existing fail-safe on ambiguous multi-flow targets (raise, don't
  mis-write) until scope-B lands flow-index coords.
- **Screen** (`screens/tone_editor.py`): add the horizontal chain render and the
  new bindings/actions (`a` add, `x` delete, `b` bypass, model-swap, output
  edit). Keep the params inspector, dirty tracking, save, and confirm-discard.
  Add-block uses a picker modal (follow `AddToneModal` / `ConfirmModal` pattern
  in `widgets/`). Update `widgets/help_overlay.py` and the key-hints footer.
- **Fake** (`tests/fake_core.py`, `FakeEditorPort`): record every structural call
  in `.calls` (mirrors the existing `save_params` recording) so screen tests
  assert on them; back the catalog + chain from an in-memory store.

No new top-level screen/tab — this extends the editor reached from Library. The
boundary rule holds (screens never import `helixgen`; only `self.app.core`).

## Error handling

- Add/delete on a **parallel** path → `OpResult(ok=False, reason)` surfaced in
  the footer; no mutation.
- Ambiguous multi-flow / dual-slot target → fail-safe: the op raises, the save
  aborts, disk is untouched, footer reports it (unchanged contract from #13).
- Bracket-bearing model / param / block names → route all user/device-derived
  text through the `rich.text.Text` / `markup=False` fix already established for
  backlog #12 (regression test per new surface).
- Leave with unsaved edits → existing confirm-discard modal.

## Testing (TDD, per repo rules)

- **`FakeEditorPort`** extended → headless Textual-pilot screen tests:
  horizontal-chain cursor navigation across lanes/paths; add on a serial path
  records the call; add/delete on a parallel path refuses and records nothing;
  swap-model; bypass toggle; output pan/level edit; input source shown
  read-only; dirty tracking + `esc`-with-dirty confirm; atomic-failure leaves no
  recorded save.
- **`RealEditor`** adapter tests (`tests/core/test_editor.py` pattern) against a
  fixture `.hsp`: add/remove/swap/bypass/output mutate the file; parallel-path
  add/remove refuse; ambiguous multi-flow fails safe with no write.
- **Markup regression** test per new text surface (`[/]`- and `[reverb]`-bearing
  fixture), per backlog #12.
- Update `tests/test_boundaries.py` / `test_shell.py` if they enumerate editor
  affordances.
- **Adversarial review** before merge — satisfied by the ralphex review pipeline
  (workspace ralphex-transition rule); this design doc committed to
  `docs/superpowers/specs/`.

## Rollout

1. **v1** (this spec): horizontal chain view + serial add/delete/swap + bypass +
   output pan/level + input display. TUI-only, no core change, no device write.
   Ships as a helixgen-tui minor (`v0.3.0`).
2. **v2**: live propagation to the active tone (device writes, LIVE badge).
3. **Scope-B**: core PRs (reorder, split/join insert, parallel edits, path
   change, input-source write, flow-index coords), each flipping on the matching
   TUI affordance. File the core-side entries against core backlog #3 when each
   starts. Update backlog **#13** as these land.

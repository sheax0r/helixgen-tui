# Plan: Signal-flow editor v1 (chain management)

## Context

Implements backlog **#13** (full chain management) plus output pan/level and
input-source surfaces, per spec
`docs/superpowers/specs/2026-07-18-signal-flow-editor-design.md`. Extends the
shipped **tone param editor v1** (`ToneEditorScreen`, v0.2.0) — do NOT rebuild
value-editing; add *structural* editing and the output/input surfaces around it.

**v1 scope (this plan): TUI-only, no core change, no device write.** All edits
go to the library `.hsp` exactly as the v0.2.0 editor does (device untouched).
Deferred (NOT in this plan): live propagation to the active tone (v2), and
reorder / split-join insert / parallel-path add-delete / path change /
input-source *write* / flow-index coords (scope-B, each needs a helixgen-core
verb first — file against core backlog #3 when started).

**Repo rules:** TDD (failing test first, Textual pilot for screens); the TUI is
view/controller over the installed `helixgen` package — no `.hsp` parsing or
protocol logic in screens, screens reach core only via `self.app.core`
(enforced by `tests/test_boundaries.py`); every user/device-derived text surface
must be markup-safe (`rich.text.Text` cells / `markup=False`), per backlog #12.

**Core capability boundary for this plan (verified against helixgen 0.26.0 —
confirm exact signatures by importing `helixgen` during implementation):**
- `helixgen.mutate.add_block` / `remove_block` — **serial paths only**; both
  raise `MutateError` if the path carries a split/join. Surface that refusal as
  `OpResult(ok=False, ...)`, never a crash.
- `helixgen.mutate.swap_model` — same-category model swap.
- block bypass/enable — a `helixgen.mutate` bypass verb (confirm the name).
- `helixgen.mutate.set_flow_param(body, "output", param, value, ...)` — output
  `level` (dB, approx −120..20) and `pan` (0..1). Full read+write.
- read output level/pan and input source (`inst1`/`inst2`/`both`/`none`) from the
  tone via `helixgen`'s view/output/input helpers (the same `.hsp` the editor
  already loads through `SetlistManifest.tone_path`).
- block model catalogue by category from `helixgen.library.Library`.

**Existing surfaces to reuse** (see pattern in `core/editor.py`, `core/ports.py`,
`core/models.py`, `screens/tone_editor.py`, `tests/fake_core.py`,
`tests/core/test_editor.py`, `tests/screens/test_tone_editor.py`):
VMs `ChainVM/PathVM/BlockVM/ParamVM/ParamChange`; `EditorPort.get_chain /
save_params`; `RealEditor` (atomic `.hsp` write: build in memory, single
`write_hsp`, disk untouched on any failure); `FakeEditorPort` (records calls in
`.calls`). Keep the existing atomic-write discipline and the fail-safe on
ambiguous multi-flow / dual-slot targets (raise `MutateError`, never a wrong-slot
write) for every new verb.

---

### Task 1: Expose output and input as chain nodes (read path)

**Files:** `src/helixgen_tui/core/models.py`, `src/helixgen_tui/core/ports.py`,
`src/helixgen_tui/core/editor.py`, `tests/fake_core.py`,
`tests/core/test_editor.py`.

- [x] Add frozen VMs to `core/models.py` matching existing conventions
  (`@dataclass(frozen=True, slots=True)`, `str | None`, `tuple[...]`):
  `OutputVM(level: float, pan: float)` and an input source representation
  (add `output: OutputVM | None` and `input_source: str | None` — one of
  `"inst1"|"inst2"|"both"|"none"` — to `ChainVM`). Default to `None` so existing
  callers/tests stay valid.
- [x] Write the failing adapter test in `tests/core/test_editor.py`: loading a
  fixture tone's chain via `RealEditor.get_chain` returns a populated
  `output` (level+pan) and `input_source`. (Reuse/extend the existing editor
  fixture `.hsp`.)
- [x] Run it, confirm it fails for the expected reason.
- [x] Implement: in `RealEditor.get_chain`, read output level/pan and input
  source from the loaded `.hsp` via the `helixgen` view/output/input helpers and
  populate the new fields. No screen change yet.
- [x] Extend `FakeEditorPort` so its in-memory `ChainVM` carries `output` and
  `input_source`, seedable per test.
- [x] Run tests, confirm pass.
- [x] Commit.

### Task 2: `set_output` verb (output pan/level write)

**Files:** `core/ports.py`, `core/editor.py`, `tests/fake_core.py`,
`tests/core/test_editor.py`.

- [x] Add to `EditorPort` (and the `Core` protocol usage stays via `editor`):
  `set_output(self, tone_id: str, level: float, pan: float) -> OpResult`.
- [x] Failing adapter test: `RealEditor.set_output` writes the output level+pan
  into the `.hsp` (assert via re-reading `get_chain().output`); a failure aborts
  before `write_hsp` leaving disk untouched (atomic contract).
- [x] Run, confirm fail.
- [x] Implement `RealEditor.set_output` over
  `mutate.set_flow_param(body, "output", "level"/"pan", value, ...)`, clamping
  pan to `[0,1]` (mirror the existing param-clamp discipline; `set_param` does
  not clamp). Atomic write.
- [x] `FakeEditorPort.set_output` records `("set_output", (tone_id, level, pan))`
  in `.calls` and updates its in-memory output.
- [x] Run tests, confirm pass. Commit.

### Task 3: `set_bypass` verb (bypass / enable toggle)

**Files:** `core/ports.py`, `core/editor.py`, `tests/fake_core.py`,
`tests/core/test_editor.py`.

- [x] Add `EditorPort.set_bypass(self, tone_id: str, block: BlockVM, enabled: bool) -> OpResult`
  (address the block by its existing `(model, lane=@path, pos=@position)`
  coordinates, same mapping `save_params` uses; ambiguous multi-flow target
  fails safe with `MutateError` → `OpResult(ok=False, ...)`).
- [x] Failing adapter test: toggling a block's `enabled` writes the `.hsp`
  (assert via `get_chain`), and an ambiguous/dual-slot target fails safe with no
  write.
- [x] Run, confirm fail.
- [x] Implement over the `helixgen.mutate` bypass verb, atomic write.
- [x] `FakeEditorPort.set_bypass` records `("set_bypass", (tone_id, coords, enabled))`.
- [x] Run tests, confirm pass. Commit.

### Task 4: Block add / remove / swap + catalogue (serial paths; parallel refuses)

**Files:** `core/models.py`, `core/ports.py`, `core/editor.py`,
`tests/fake_core.py`, `tests/core/test_editor.py`.

- [ ] Add `BlockCatalogVM(category: str, models: tuple[tuple[str, str], ...])`
  (each entry `(model_id, display)`), frozen.
- [ ] Add to `EditorPort`:
  `list_block_catalog(self) -> tuple[BlockCatalogVM, ...]`,
  `add_block(self, tone_id: str, after: BlockVM | None, model: str) -> OpResult`,
  `remove_block(self, tone_id: str, block: BlockVM) -> OpResult`,
  `swap_model(self, tone_id: str, block: BlockVM, model: str) -> OpResult`.
- [ ] Failing adapter tests: add-after-block and remove on a **serial** path
  mutate the `.hsp`; swap replaces the model in place; add/remove on a
  **parallel** path (split/join present) returns `OpResult(ok=False, ...)` with a
  clear reason and does **not** write; every failure path leaves disk untouched.
- [ ] Run, confirm fail.
- [ ] Implement over `mutate.add_block(..., after=...)` / `mutate.remove_block` /
  `mutate.swap_model`; catch `MutateError` (incl. the parallel-path refusal) and
  return `OpResult(ok=False, message=<reason>)`. Read the catalogue from
  `library.Library`. Atomic write per op.
- [ ] `FakeEditorPort` records `("add_block", ...)`, `("remove_block", ...)`,
  `("swap_model", ...)` in `.calls`; models a serial vs parallel path so refusal
  is testable; serves a small catalogue.
- [ ] Run tests, confirm pass. Commit.

### Task 5: Horizontal chain view in the tone editor (render + navigation)

**Files:** `src/helixgen_tui/screens/tone_editor.py`,
`tests/screens/test_tone_editor.py` (and `tests/test_boundaries.py` /
`tests/test_shell.py` only if they enumerate editor internals).

- [ ] Failing pilot test: opening the editor on a fake tone renders a
  **horizontal** chain surface (left-to-right, one row per lane, both DSP paths
  stacked when present, split/join drawn with `+`/`-` connectors), with the
  input source shown as the head node and the output (level/pan) as the terminal
  node; the cursor starts on the first block and moves along the lane / across
  lanes+paths with the nav keys. Assert the rendered chain contains the fake's
  block displays and the output/input nodes, and that cursor movement changes the
  selected block feeding the params inspector.
- [ ] Run, confirm fail.
- [ ] Implement the horizontal render as the block-selection surface (the
  primary navigator; keep the params inspector, dirty tracking, save, and
  confirm-discard from v0.2.0). All block/model/param/output text rendered
  markup-safe (`rich.text.Text` / `markup=False`, per backlog #12). Chain wider
  than the pane scrolls horizontally. Selecting the output node shows its
  pan/level in the inspector; selecting the input node shows the source
  read-only.
- [ ] Run tests, confirm pass. Commit.

### Task 6: Structural + output actions wired to the screen

**Files:** `src/helixgen_tui/screens/tone_editor.py`,
`src/helixgen_tui/widgets/` (a block-picker modal, following `AddToneModal` /
`ConfirmModal`), `src/helixgen_tui/widgets/help_overlay.py`,
`tests/screens/test_tone_editor.py`, `README.md`.

- [ ] Failing pilot tests (assert on `FakeEditorPort.calls`, footer text, dirty
  state):
  - `a` on a block in a **serial** path opens the block-picker modal; choosing a
    model records `("add_block", ...)` and marks the editor dirty;
  - `a`/`x` on a **parallel** path refuses with a footer reason and records
    nothing;
  - `x` on a serial block records `("remove_block", ...)`;
  - `b` records `("set_bypass", (…, enabled_flipped))`;
  - model-swap on a block records `("swap_model", ...)`;
  - editing the **output** node's pan/level records `("set_output", ...)` and
    goes dirty; `s` still saves via the existing save path;
  - the **input** node is read-only (no write action available).
- [ ] Run, confirm fail.
- [ ] Implement: add `BINDINGS` + `action_*` handlers (`a` add, `x` delete,
  `b` bypass, a swap affordance, output pan/level edit reusing the inspector's
  nudge/manual-entry mechanics from v0.2.0). Add the block-picker modal
  (category → model; markup-safe). Route refusals through the status footer.
  Update `help_overlay.py` and the key-hints footer with the new keys; update the
  `README.md` editor/keys description.
- [ ] Run tests, confirm pass. Commit.

---

## Validation Commands

Run from the repo root:

- `uv run pytest` — full offline suite (Textual pilot screen tests use fake
  services; no device required).
- `uv run ruff check .` — lint.

No live-device test is needed for this plan — v1 never touches the device.

# helixgen-tui backlog

Numbering is local to this repo. The originating entry is helixgen-core's
backlog #29 (helixgen-tui), which carries the product mandate: cover
everything the Stadium desktop app does, slots invisible, own design spec
before any code.

- ✅ **#1 Design spec + v1 librarian** — shipped 2026-07-17:
  `docs/superpowers/specs/2026-07-17-tui-v1-librarian-design.md` and its
  8-task implementation plan
  (`docs/superpowers/plans/2026-07-17-tui-v1-librarian.md`), both fully
  built: Textual shell, tabbed Library/Setlists/IRs/Device screens,
  offline-first device handling, tiered mutation confirmation, direct Python
  API behind the `helixgen_tui.core` adapter, layered fake-core + Pilot
  testing. Released as `v0.1.0`.
- ✅ **#2 Packaging + CI skeleton** — shipped 2026-07-17 (PR #1): pyproject
  (`helixgen-tui`, `helixgen[device]>=0.26`), console script + `-m` entry,
  pytest + ruff CI, publish workflow.
- **#3 Ask core to bless a minimal stable Python API surface** for the TUI's
  needs (library/manifest/device reads, mutation verbs, locks) — the TUI
  binds the Python API directly (design D5); today only the CLI is core's
  documented contract. File the core-side entry when implementation starts
  and the real import list is known.
- **#4 Tone-designer chat screen (first post-v1 screen)** — user-requested
  2026-07-17: if Claude Code is installed locally, a fifth tab hosts a
  conversation where the user describes a tone and Claude authors it into
  the library via the helixgen plugin skills. Requirements (auth reuse,
  D4-modal permission bridging, graceful degradation, library refresh) are
  settled in the v1 design spec's "first post-v1 screen" section; binding
  choice (Agent SDK vs headless CLI) deferred to build time.
- **#5 Live smoke suite (`HELIXGEN_TUI_LIVE=1`)** — deferred per spec D6;
  validate `RealDevicePort` verbs on hardware. The v1 build's device tests
  are entirely `FakeDevicePort`-driven (no real hardware in CI or dev); this
  entry tracks writing an opt-in, env-gated suite that exercises the real
  port's per-verb delegations against an actual Helix Stadium.
- **#6 Core Python verbs missing for restore-with-cid, tone delete, single-tone
  push** — `RealDevicePort` returns `ok=False` for these; the engine change
  lands in helixgen-core first (ref #3's stable-API ask).
- **#7 Shipped-vs-spec deltas (consciously deferred in the v1 plan)** — recorded
  at v1 release so the gaps are tracked, not forgotten. Each was scoped out in
  the implementation plan, not missed:
  - **Device-side setlists pane** — the Setlists screen edits the local
    manifest only; a read-back of what's actually mirrored on the device is
    future work.
  - **Sortable tone list** — the Library table renders in library order with a
    substring filter; column sorting isn't wired.
  - **Detail-view variants + normalized telemetry** — `ToneDetailModal` shows
    name/guitar/setlists/description; per-guitar variants and normalized
    loudness/telemetry from the tone meta aren't surfaced.
  - **`--gc` from the UI** — `sync_all` always passes `gc=False`; the
    pool garbage-collect toggle is exposed on the CLI only.
  - **Tab-cycling** — modes are reached by their number keys (`1`–`4`); there's
    no `tab`/`shift+tab` cycle between them.

- **#8 Cosmetic minors from the final review (2026-07-17)** — (a) modal
  dismissal fires `ScreenResume`, rebuilding tables and resetting DataTable
  cursors to row 0 (flows unaffected; selection captured pre-modal);
  (b) device screen `r` retry needs a second press after reconnect under the
  production spawn (probe async, info refresh immediate); (c) format_device_text
  substring heuristic is fragile; (d) library filter matches name only.

## 9. v0.1.1 residuals (from PR #14 review)

- Device-pane delete/rename still resolve IRs by display name first-match on the
  device — acting on a duplicate-named *device* IR may hit the wrong entry.
  Local-pane push was fixed in v0.1.1 (pushes by irhash); the device side needs
  hash-addressed core verbs (relates #6).
- Upstream Textual bug worth reporting: on Python >= 3.12, `run_async` installs
  `asyncio.eager_task_factory`, so a MODES app whose default screen contains an
  `Input` crashes at boot (`ScreenStackError` from the selection watcher —
  `App.clear_selection` only catches `NoScreen`). We carry a `clear_selection`
  override in `app.py`; drop it once fixed upstream (textual 8.2.8 affected).
- `App.screen` can also raise `UnknownModeError` (not caught by our override);
  believed unreachable — noted in case a teardown-phase variant ever appears.
- IR selection helpers now index into the backing list and would raise
  `IndexError` on a table/list mismatch instead of degrading to None —
  intentional fail-fast, noting the behavior change.

## 10. Fuzzy search everywhere (user request, 2026-07-18)

Type part of a name to find/use the thing, wherever a list is presented:
selecting a setlist, picking a tone in the add-tone modal, the library tone
list, local/device IR panes. Today only the Library screen has a filter
(`/`), it matches name-substring only (see #8), and the pickers/panes have
none. Wants: incremental fuzzy matching (subsequence or trigram), highlight
of matches, and enter-to-act on the top hit.

## 11. Key-hints footer polish (from PR #16 review)

- At narrow widths (~80 cols) the bindings footer silently scrolls trailing
  keys out of view on binding-heavy screens (setlists) — consider compact
  key-only display or priority ordering.
- The footer also exposes Textual's command palette (^p: theme, screenshot,
  …). Decide whether that's intended product surface or should be disabled
  (`ENABLE_COMMAND_PALETTE = False`).

## 12. Console-markup bug class beyond the detail modal (from PR review, 2026-07-18) — RESOLVED

Swept in plan `docs/plans/2026-07-18-12-markup-safety.md` (branch
`12-markup-safety`): DataTable cells wrapped in `rich.text.Text` (library,
setlists incl. AddToneModal, irs local+device), `ConfirmModal` and
`DeviceScreen` info/locks Statics set `markup=False`. Regression test per
surface with `[/]`/`[reverb]` fixtures. Original entry below for history.

The tiny-empty-box fix (PR: `ToneDetailModal` → `markup=False`, shipped
v0.1.3) closed one instance of a repo-wide bug: any Textual surface that
renders tone/device-derived free text with markup parsing on will strip
bracket-bearing text (`[reverb]`, `[b]…[/b]`, `[text](url)`) and **crash the
whole screen** on a malformed tag (a tone named `Bad [/] name` raises
`MarkupError`). Confirmed instances still open:
- **DataTable cells (highest severity, highest traffic).** `library.py`,
  `setlists.py`, `irs.py`, and the `AddToneModal` picker pass plain-string
  cells; Textual's `default_cell_formatter` runs `Text.from_markup` on each.
  A bracketed tone name renders corrupted in the library table *before* the
  detail modal is reachable, and a `[/]`-bearing name crashes the screen on
  load. `markup=False` does not apply to DataTable — pass `rich.text.Text`
  cell objects (a `Text` bypasses the markup parse).
- **`ConfirmModal` (`widgets/confirm_modal.py`).** `Static(body)` is
  markup-parsed and `body` includes `plan.lines` built from
  `f"{tone.name} …"`, so a bracketed tone name is stripped / a `[/]` name
  crashes the confirm dialog. Also its hardcoded `"[y] confirm  [n] cancel"`
  footer is silently stripped to `" confirm   cancel"` today — the key hints
  are invisible in the shipped product. Fix: `markup=False` + restyle/escape
  the footer.
- **`DeviceScreen` info/locks Statics (`device.py`).** `_apply_info` writes
  `f"Active tone: {state.active_tone}"` and `_apply_locks` writes free-text
  lock labels (`--label "<who>"`) into default-markup Statics — same class,
  lower traffic.

Do a single sweep converting user/device-derived text surfaces (Text cells
for tables, `markup=False` for Statics) with a regression test per surface
using a `[/]`- and `[reverb]`-bearing fixture.

## 13. Full chain management (from tone param editor v1, 2026-07-18)

The tone param editor (`ToneEditorScreen`, v0.2.0) edited **values on existing
blocks only**. Signal-flow editing (this branch, 2026-07-18, plan
`docs/plans/2026-07-18-signal-flow-editor.md`) shipped part of the structural
scope; the rest stays deferred here:

- **Add / remove / swap blocks — SHIPPED (serial paths only).** `a`/`x`/`w` in
  the tone editor over `helixgen.mutate` add/remove/swap verbs; parallel-routed
  paths refuse (records nothing). Reorder within a lane is still deferred (below).
- **Bypass/enable toggle — SHIPPED.** `b` toggles a block's enabled/bypassed
  state via `set_bypass`.
- **Output level/pan editing — SHIPPED.** The output terminal node is an
  editable row (level/pan) written via `set_output`. Input source stays
  **read-only** (input-source *write* deferred, below).
- **Reorder blocks, splits, and parallel paths.** Reordering, authoring
  splits/parallel lanes, parallel-path add/delete, path change, and
  **input-source write** are **author-time only** in core today (the runtime
  `mutate` surface doesn't reorder, create splits, or write input source) — this
  is **net-new core work** (file the core-side entry against #3's stable-API ask
  when it starts). Flow-index coordinates (below) are a prerequisite for
  addressing parallel/multi-flow targets.
- **Multi-flow / dual-slot editing (adversarial-review finding, 2026-07-18).**
  `RealEditor.get_chain` flattens blocks by lane (`@path`) only — it has no flow
  index (`extract_blocks_from_hsp` doesn't expose it) — and iterates every raw
  block, including *both* slots of a dual-cab (while `mutate.set_param` resolves
  only slot 0). Effects, all **fail-safe** (never a wrong-slot write — an
  ambiguous target raises `MutateError` and the save fails): (a) two blocks with
  the same `(model, lane, pos)` across different DSP flows alias to one editor
  row and can't be saved; (b) a dual-cab's second slot shows as an editable row
  whose save fails with "not in preset". Cabs are common, so this is a real UX
  wart. Proper fix needs flow-index-aware coordinates from core (ref #3) so the
  editor can address and write every slot; until then the editor is honest about
  the failure rather than corrupting the file.

## 15. Tone-editor header cosmetic clipping (adversarial-review, 2026-07-18)

The v0.2.1 header-overflow fix pins `#editor-header` to a fixed `height: 4`
(hard clip in Textual, verified: a 90-char name + 300-char description still
holds the box to 4 rows and never eats the tables — the actual bug can't
recur). Remaining, purely cosmetic: within that 4-row box, an unusually long
tone **name** (name + `   * unsaved` past the terminal width) wraps and can
push the `Description:` line out of view, and a 100-char compacted description
plus its `Description: ` prefix wraps to two rows on a narrow (~80-col)
terminal. Nothing is lost destructively and no other pane is affected. If it
ever bothers a user: budget the header by terminal width (truncate name too,
size `_DESC_MAX` off the available columns) instead of a flat 100. Low
priority — no functional impact.

## 14. Param-schema enrichment dependency on core (from tone param editor v1)

The editor reads per-param **type** and **default** from `library.Library`'s
block schema, and infers the type from the current value when a block isn't
catalogued. It has no access to authoritative info the UX wants:

- **Real ranges** — `observed_range` is explicitly not authoritative, so the
  editor clamps floats to a hardcoded `[0.0, 1.0]` and applies no bound to ints.
- **Enum labels** — no enum/choice metadata, so enum-like params are nudged as
  bare ints with no human labels.
- **Step / units / display names** — none available; the editor uses a fixed
  0.01 float step and shows raw param keys.
- **Range validation in `mutate.set_param`** — `set_param` validates name+type
  but does **not** clamp/validate ranges, so the TUI must enforce bounds itself.

This is the content of existing **#3** (bless a stable core Python API surface)
applied to param editing — cross-referenced here so the editor's schema needs
are captured. Land the enrichment in helixgen-core first, then the editor can
drop its hardcoded clamp and surface real ranges/enums/units.

## 16. Signal-flow editor: chain navigator polish (adversarial-review, 2026-07-18)

Deferred from the signal-flow-editor review. None are correctness/data bugs —
the chain fits-on-screen case works and every write path is atomic + fail-safe.

- **Cursor doesn't scroll into view on wide chains.** Task 5's "chain wider than
  the pane scrolls horizontally" is only half-met: `#editor-chain-wrap` has
  `overflow-x: auto`, but left/right are bound at the screen level for
  navigation so they never reach the container's scroll actions, and nothing
  calls `scroll_to`/`scroll_visible`. On a chain wider than the pane (8 blocks
  with ~18-char labels can exceed 80 cols) the selected block can sit off-screen
  with no keyboard way to reveal it. Fix: after `_render_chain`, compute the
  selected node's column offset and `scroll_to_region`/`scroll_to` the wrap
  container so the cursor follows. Fits-on-screen tones are unaffected.
- **Swap picker mislabels itself and offers cross-category models.** Invoked via
  `w`, `BlockPickerModal` still titles itself "Add block — pick a category" and
  lists every category; picking a different category fails soft (core
  `swap_model` refuses with `MutateError` → footer) but is confusing. Fix:
  parameterize the modal title and, for swap, pass/pre-select only the block's
  own category.
- **Partial save leaves a transiently stale dirty flag.** `action_save` runs
  `save_params` then `set_output` independently; if the first persists and the
  second fails, `all_ok` is false so `_reload_chain` is skipped — the param
  edits are on disk yet `self._edits` still reads dirty. Self-corrects on the
  next (idempotent) save; no data loss. Fix: clear the portion that succeeded,
  or reload unconditionally and re-stage only what still differs.

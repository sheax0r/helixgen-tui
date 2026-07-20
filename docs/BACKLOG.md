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
    subsequence fuzzy filter; column sorting isn't wired.
  - **Detail-view variants + normalized telemetry** — `ToneDetailModal` shows
    name/guitar/setlists/description; per-guitar variants and normalized
    loudness/telemetry from the tone meta aren't surfaced.
  - **`--gc` from the UI** — `sync_all` always passes `gc=False`; the
    pool garbage-collect toggle is exposed on the CLI only.
  - **Tab-cycling** — modes are reached by their number keys (`1`–`4`); there's
    no `tab`/`shift+tab` cycle between them.

- **#8 Cosmetic minors from the final review (2026-07-17)** — (a) modal
  dismissal fires `ScreenResume`, rebuilding tables and resetting DataTable
  cursors to row 0 — **RESOLVED 2026-07-18** (tui-polish plan, Task 1):
  `_capture_cursor_key`/`_restore_cursor_key` in `screens/base.py` hold the
  cursor across the rebuild on all three list screens (setlists tones pane
  preserved only across same-setlist rebuilds);
  (b) device screen `r` retry needs a second press after reconnect under the
  production spawn (probe async, info refresh immediate); (c) format_device_text
  substring heuristic is fragile; (d) filters match name only — the pickers and
  panes all gained filters in #10 (RESOLVED 2026-07-19) and matching is now
  scored fuzzy, but every surface still matches the primary name text only;
  multi-field matching is #18.

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

## 10. Fuzzy search everywhere (user request, 2026-07-18) — RESOLVED 2026-07-19

Shipped in plan `docs/plans/completed/2026-07-19-fuzzy-search-everywhere.md` (branch
`fuzzy-search-everywhere`): a scored matcher in `src/helixgen_tui/fuzzy.py`
(pure, no Textual/Rich), a shared `FilterableTableMixin`
(`src/helixgen_tui/screens/filterable.py`) wiring a filter `Input` to a
`DataTable`, and rollout to all four surfaces — Library, the Setlists left
pane, `AddToneModal`, and both IR panes (one filter, targeting the focused
pane). Results re-sort best-first while a query is active, matched characters
are highlighted, and `enter` acts on the top hit *without* mutating the device
(Library/Setlists/IRs move the cursor only; the modal dismisses with the tone).
The IR panes' positional `str(index)` row-key lookups were retired in favour of
the mixin's `_visible` list.

Original wants: type part of a name to find/use the thing, wherever a list is
presented — setlist selection, the add-tone modal, the library tone list,
local/device IR panes, with match highlighting and enter-to-act on the top hit.

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

## 17. Signal-flow editor v2: live propagation to the active tone (from #13, 2026-07-18)

The v0.3.0 signal-flow editor is **library-`.hsp`-only** — every edit writes the
tone file, the device is never touched (same contract as the param editor).
v2 makes editing the **currently-active** device tone propagate live:

- **Param-class edits propagate live.** Output pan/level, block params, bypass,
  and same-category model swap map onto core's live device verbs
  (`device set-param` / `bypass` / `model`) — push them to the edit buffer as the
  user edits, so the active tone changes in real time.
- **Structural edits stay local, marked "save to hear."** Add/remove/swap of a
  block has no live device protocol (core `mutate` is file-only), so these carry
  a marker and only take effect on the device at the next explicit save.
- **LIVE badge + write-gating.** Show the editor is bound to the active tone;
  device writes stay explicit/visible per the product's write-gating rule, never
  a navigation side effect. The **saved slot** updates only on `s` — live
  propagation edits the edit buffer, not the stored preset, until save.
- Deferred from v1 to keep the first editor release device-free. Needs the
  active-tone binding + edit-buffer sync plumbing that v1 has no equivalent of.
  Depends on nothing in core beyond what already ships (live verbs exist);
  purely TUI work.

## 18. Multi-field fuzzy match (deferred from #10, 2026-07-19)

Every filter shipped in #10 matches the surface's **primary name text only**.
Wants: match (and highlight) additional fields — Library tone `guitar` and
`description`, IR pack name / hash — so `strat` finds tones tagged with that
guitar. Needs a decision on how a multi-field score combines (max-of-fields vs
weighted sum) and where the highlight lands when the hit is not in the name
column. `FilterableTableMixin` would grow a `filter_fields(item)` hook beside
the existing `filter_text(item)`.

## 21. Filter keystrokes do more work than they need to (review finding, 2026-07-19)

Not a defect — no user-visible lag at present library/IR sizes — but two paths
rebuild more than the keystroke changed:

- `IrsScreen._on_filter_changed` calls `_rebuild_panes()`, which rebuilds
  *both* panes. The inactive pane reports an empty query, so its rows are
  byte-identical every time; only a focus switch can change them, and
  `on_descendant_focus` already rebuilds for that. Could be
  `self._active_pane().rebuild_filtered()`.
- `SetlistsScreen._on_filter_changed` calls `_rebuild_tones_table()`, which does
  one `library.get_tone()` per tone in the selected setlist, on every character
  typed.
- `FilterableTableMixin.rebuild_filtered` calls `filter_text(item)` twice per
  item per keystroke (once to match, once to build the label).

Worth revisiting if a large library ever makes typing feel sticky; measure
before optimising.

## 19. `BlockPickerModal` fuzzy filter (deferred from #10, 2026-07-19)

`src/helixgen_tui/widgets/block_picker_modal.py` (tone editor
category → model picker) is the one remaining unfiltered list surface. It was
held back from #10 to keep that change scoped to the librarian screens.
`FilterableTableMixin` fits it as-is: `filter_text` = the model name,
`filter_on_enter` = dismiss with the picked model, same enter/escape contract
as `AddToneModal`.

## 20. Shared `ModalScreen` base for the pickers (2026-07-19)

`AddToneModal` (`screens/setlists.py`) and `BlockPickerModal`
(`widgets/block_picker_modal.py`) carry near-identical `DEFAULT_CSS`, compose
shape (title + `DataTable`), and escape-cancel behavior — and after #19 they
will share the filter wiring too. Factor out a common picker base so the layout
and the escape/enter contract are defined once. Cosmetic/structural only; no
behavior change intended.

## 22. IR pane cursor can drift between identical rows (review finding, 2026-07-19)

`_IrPane.filter_identity` (`screens/irs.py`) is `(name, pack, irhash)`, which is
not a true primary key: an IR library can hold genuinely identical duplicate
entries (`test_repeated_ir_instance_renders_as_two_rows` covers the rendering
side). `move_cursor_to` returns the *first* match, so a cursor parked on the
second duplicate snaps back to the first on any rebuild. The positional
`_restore_cursor_key` this replaced preserved it, so it is a small regression —
accepted because the rows are indistinguishable: both resolve to the same
`push_ir(irhash or name)` / `delete_ir(name)` target, so no wrong device write
is reachable. Fix if it ever becomes visible: have `move_cursor_to` prefer the
candidate at or after the previous cursor row, or carry backing position in the
identity for panes whose items can be fully identical.

## 23. `_renamed_to` can be consumed by an unrelated refresh (review finding, 2026-07-19)

`IrsScreen._restore_renamed_cursor` (`screens/irs.py`) stores the pending name at
rename submit and clears it in whichever `_apply_device_irs` runs next. If an `r`
or a `ScreenResume` refresh interleaves before the rename's own
`RefreshDeviceIrsRequested` lands, that earlier refresh sees the pre-rename list,
matches nothing, and clears the pending restore — leaving the cursor at row 0 on
the real post-rename refresh. Same outcome when a live filter excludes the new
name. Low likelihood and mitigated: `d` shows its plan in `ConfirmModal` before
deleting anything. Fix: consume `_renamed_to` only on the `_apply_device_irs`
triggered by `RefreshDeviceIrsRequested`, or leave it set until it matches.

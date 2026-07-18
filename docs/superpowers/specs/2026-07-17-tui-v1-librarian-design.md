# helixgen-tui v1 — the librarian: design spec

**Date:** 2026-07-17
**Status:** approved (brainstormed with the user; every decision below was an
explicit choice among presented alternatives)
**Closes:** this repo's backlog #1 (design spec); tri-repo backlog #29/#60
**Builds on:** the #2/#61 packaging + CI skeleton already on `main`

## Product frame (settled before this spec)

- **V1 is the librarian:** browse and manage tones, setlists, sync, and IRs,
  plus setting the **active tone** on the device.
- **Slots are invisible.** The UI speaks in tones and setlists only; slot
  addresses (`1A`..`8D`) never appear anywhere in the interface. Ordering is
  expressed as list order, nothing else. Non-negotiable (core backlog #29).
- **The shell hosts switchable screens from day one.** Future surfaces
  (signal-flow editor, global settings, tuner/meters) arrive as new screens,
  not rewrites.
- **Engines live in core.** No protocol logic, no `.hsp` parsing, no hashing
  in this repo. If the TUI needs an engine change, it lands in helixgen-core
  first.
- **Device writes are real** and must be explicit, visible user actions —
  never side effects of navigation.

## Decisions

Each was chosen from 2–3 presented alternatives; the rejected options and the
reasons are recorded here so they aren't re-litigated.

### D1. Stack: Textual

Textual (Textualize) is the UI framework.

- Built-in multi-screen support (`Screen`/`ModalScreen`/tabs) matches the
  switchable-screens mandate directly.
- Async-first fits the flaky device network: device I/O runs in workers and
  can never freeze the UI thread.
- First-class headless test harness (Pilot) fits the repo's TDD rule.
- Rich widget set (DataTable, Tree, Tabs) covers the librarian's needs
  without hand-rolling.

Rejected: **urwid** (mature but everything manual — no screen stack, sparse
widgets, no real testing story) and **stdlib curses** (zero deps but you build
the entire framework yourself; core's stdlib-only rule deliberately does not
bind this repo).

### D2. Navigation: tabbed top-level screens

Top-level switchable screens selected by number keys / tab cycling, one noun
per screen, with a persistent status footer:

```
┌ hxg ─ [1]Library [2]Setlists [3]IRs [4]Device ────┐
│ Tones                                    47 tones │
│ ▸ AC/DC - Back in Black - SG      ✓ synced        │
│   Foo Fighters - Everlong - LP    ○ local only    │
│                                                   │
│ [enter] details  [a] make active  [s] sync…       │
└─ device: Stadium XL ● connected ──────────────────┘
```

Future screens become tabs 5+. Rejected: a single miller-column workspace
(denser but hard to extend with non-librarian screens) and a
command-palette-first shell (poor discoverability; v1's job is making the
library *browsable*). Textual's built-in command palette remains available as
a bonus, not the primary navigation.

### D3. Offline behavior: offline-first

The app always starts instantly against local state (`$HELIXGEN_HOME`
library + setlist manifest) and never blocks on the device.

- Device connectivity is a footer status (`● connected` / `○ offline ·
  retrying`), not a gate to launch.
- `DeviceService` probes in the background: persisted device records first
  (core backlog #74), discovery as fallback; automatic reconnection with a
  manual retry key.
- Device-dependent panes (on-device presets, device IRs) show an
  "unavailable — device offline" state; device-mutating actions are disabled
  with a visible reason, never hidden.
- Matches core's local-file-first principle: the librarian is fully useful
  with no device on the network.

Rejected: connect-on-launch (blocks startup on a flaky network the main v1
surface doesn't even need) and explicit-connect-only (manual step before
every device interaction, stale state on Wi-Fi drops).

### D4. Mutation confirmation: tiered

Friction proportional to blast radius:

- **Instant on keypress** (the keypress *is* the explicit action):
  make-active on an already-synced tone, single-tone sync. Result reported in
  the footer.
- **Confirm modal showing the concrete plan** (fed by the operation's
  dry-run/plan data, listing exactly what will change): delete, `ir-prune`,
  `sync --all`/`--gc`, restore, install-then-activate. `y` confirms,
  `n`/`esc` cancels.

Rejected: confirm-everything (two keystrokes for the bread-and-butter
audition loop) and a staged-changeset commit model (wrong for make-active,
which you want *now*, while playing; adds a staging state machine v1 doesn't
need — worth revisiting if bulk setlist reorganization becomes a pain point).

### D5. Core binding: direct Python API behind one adapter package

The TUI imports helixgen's Python modules in-process (no subprocess per
action, natural async wrapping, direct access to streaming surfaces like
watch/meters for future screens).

The risk — core's *documented* contract is the CLI, not the Python API — is
contained structurally: **`helixgen_tui.core` is the only package allowed to
import `helixgen`.** Screens and widgets consume frozen view-model
dataclasses from the adapter and never touch helixgen objects. Core-internals
churn therefore lands in one package. Follow-up (tracked in the backlog): ask
core to bless a minimal stable API surface for the TUI's needs.

Rejected: CLI subprocess + `--json` (rides the documented contract but
process-per-keypress, no streaming, lock tokens via env juggling) and a
hybrid (doubles the adapter surface; the seams show).

### D6. Testing: layered — fake core + Pilot

1. **Adapter tests:** `helixgen_tui.core` runs against a real temporary
   `HELIXGEN_HOME` (real manifest/metadata code paths, no device). Guard that
   tests never touch the real home (port core's live-suite guard; core
   backlog #79(k) is the cautionary tale).
2. **Screen tests:** Textual Pilot drives the app headless against a
   `FakeCore` adapter with scripted behavior — including offline transitions,
   mid-operation drops, timeouts, and lock contention, which are hard to
   produce against hardware.
3. **Live smoke suite:** opt-in (`HELIXGEN_TUI_LIVE=1`), mirroring core's
   `tests/live` pattern. **Deferred until after v1.**

TDD throughout, per repo rules. Snapshot testing (pytest-textual-snapshot)
was considered and deferred: golden-file churn during v1's rapid UI iteration
outweighs the regression value; revisit once the UI stabilizes.

## Architecture

```
src/helixgen_tui/
  __main__.py      # entry point (exists; will launch the App)
  app.py           # App subclass: tab shell, footer, global keys, theme
  core/            # the ONLY package importing helixgen  (D5)
    models.py      # frozen view-model dataclasses (ToneVM, SetlistVM, IrVM…)
    library.py     # tones/guitars/IR metadata → view models
    setlists.py    # manifest v3 read/write, membership, ordering
    device.py      # DeviceService: connectivity, reads, mutation pipeline
    locks.py       # scope leases (editbuffer/library/irs) around mutations
  screens/         # library.py, setlists.py, irs.py, device.py
  widgets/         # tone table, confirm modal, status footer, help overlay
tests/
  core/            # adapter tests (temp HELIXGEN_HOME)
  screens/         # Pilot tests against FakeCore
  fake_core.py     # scripted FakeCore adapter
```

**DeviceService** owns all device I/O. It starts disconnected, probes in the
background, exposes reactive connectivity state (footer and screens
subscribe), and runs every device call in a Textual worker with a timeout.

**View models are frozen dataclasses** built in the adapter. A screen render
never triggers I/O; data arrives via explicit refresh paths.

## Screens

### [1] Library (default screen)

- Tone list from the local library: `$artist - $song - $guitar` names, sync
  state per tone (✓ synced / ○ local-only, derived from core's recorded
  install state — content-drift detection only if core exposes it; no
  device reads just to render the list), sortable/filterable.
- `enter` — detail view: variants, guitar profile, description,
  `normalized` telemetry summary.
- `a` — make active: for a tone already on the device, instant
  (`load`, editbuffer lock); for a local-only tone, an
  install-then-activate confirm modal (bigger write → D4 modal tier).
- `s` — sync this tone.

### [2] Setlists

- Local manifest setlists (with sync-on/off state) alongside device setlists.
- Membership: add/remove tones; reorder by moving tones up/down (list order
  only — slots invisible).
- Sync one setlist; `sync --all` and `--gc` as confirmed bulk actions with
  per-tone result reporting.

### [3] IRs

- Local IR library (packs, metadata sidecars) and device IRs side by side.
- Push, rename, delete; prune shows the dry-run plan in its confirm modal.

### [4] Device

- Device info, discovery, currently active tone.
- Backup (read-only, instant); restore (confirm modal).
- Lock status with holder labels.

**Global chrome:** number keys / tab-switch; persistent footer (device
state · last action result); `?` help overlay listing keybindings per screen.

## Data flow

- **Local reads** (library, manifest) are cheap: re-run on screen entry and
  on explicit `r` refresh.
- **Device reads** are on-demand, cached per screen with a visible staleness
  marker. No aggressive polling on the flaky network.
- **Mutations** all follow one pipeline:
  confirm (if D4 modal tier, fed by dry-run data) → acquire matching lock
  scope → run in worker with timeout → report result to footer → invalidate
  affected caches. Reads take no locks (matching core's CLI behavior).

## Error handling

- Every device call has a timeout; failures surface in the footer with a
  retry affordance. The app never crashes or hangs on device errors.
- A mid-operation drop flips the app to offline state; device actions become
  disabled-with-reason; background reconnection resumes.
- Lock contention reports the holder's label (core ≥0.22.0 advisory locks).
- Mutation failures state what was and wasn't applied — sync reports
  per-tone results, never all-or-nothing silence.

## Packaging & CI (delta over the shipped #2/#61 skeleton)

Already on `main`: pyproject (`helixgen-tui`, `helixgen[device]>=0.26`,
Python ≥3.11), console script, pytest + ruff CI, publish workflow.

This design adds:

- `textual` as a runtime dependency (pin a floor, e.g. `textual>=0.60`;
  exact floor chosen at implementation time).
- A short console-script alias **`hxg`** alongside `helixgen-tui`.
- `pytest-asyncio`/Pilot test deps in the `dev` extra as needed.

## Build order

1. ~~Packaging + CI skeleton~~ — **done** (#2/#61, on `main`).
2. App shell: tabs, footer, keybindings, help overlay; Pilot harness +
   FakeCore scaffolding.
3. `core/` adapters (models, library, setlists) + Library screen, read-only.
4. DeviceService: connectivity lifecycle + offline-first footer; make-active
   and single-tone sync (first mutations, both D4 tiers).
5. Setlists screen (membership, ordering, setlist/bulk sync).
6. IRs screen.
7. Device screen + polish (locks display, backup/restore).

Each step lands as its own PR with adversarial review per repo rules.

## First post-v1 screen: the tone designer (Claude chat)

Named here (backlog #4) so the shell's first extension is designed against
real requirements, but explicitly **not v1 scope**.

A fifth tab hosting a conversation with locally-installed Claude Code: the
user describes the tone they want ("warm jazz clean, ES-335", "the Everlong
chorus sound") and Claude designs it and writes it into the library using the
existing helixgen plugin skills (`/tone`, `/setup`) — the TUI contributes no
tone logic, preserving the engine/skill boundary.

Requirements settled now:

- **Reuse the user's existing Claude Code auth.** Two viable bindings, both
  verified against current docs: the Claude Agent SDK for Python
  (`claude-agent-sdk` — native async, structured messages, `can_use_tool`
  permission callback) or headless CLI (`claude -p --output-format
  stream-json --include-partial-messages`, which rides `claude login`).
  Auth reuse is the requirement; the implementation picks the binding that
  satisfies it at build time (SDK auth expectations are version-dependent).
- **Permissions render as D4 modals.** When Claude wants to run a tool, the
  TUI intercepts (SDK `can_use_tool`, or pre-allowed `Bash(helixgen *)` on
  the CLI path) and shows the same confirm-modal language as every other
  mutation. Routine library authoring can be pre-allowed; device writes keep
  their tiers.
- **Graceful degradation, same as offline-first:** detect via
  `shutil.which("claude")` + version check; when absent, the tab is hidden
  or shows an install hint. Claude Code is an optional runtime dependency,
  exactly like the device.
- **Library refresh on completion:** the Library screen's re-read-on-entry
  already picks up new tones; the chat screen additionally signals a
  refresh when a session that wrote to the library ends.

## Out of scope for v1

- The tone-designer chat screen above (first post-v1 screen, backlog #4).
- Signal-flow editor, global settings, tuner/meters screens (the shell is
  ready for them; they come later).
- Live smoke test suite (deferred; D6).
- Snapshot testing (deferred; D6).
- Any engine work — anything protocol- or format-shaped goes to
  helixgen-core with a backlog entry.

# helixgen-tui v1 Librarian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1 librarian TUI (Library/Setlists/IRs/Device tabbed screens, offline-first device handling, tiered mutation confirmation) per the approved spec `docs/superpowers/specs/2026-07-17-tui-v1-librarian-design.md`.

**Architecture:** A Textual app whose screens render frozen view-model dataclasses obtained from a `Core` facade. `helixgen_tui.core` is the ONLY package that imports `helixgen`; screens/widgets depend on port protocols so tests substitute a scripted `FakeCore`. All device I/O flows through a `DeviceService` running calls in thread workers with timeouts — offline-first, never blocking the UI.

**Tech Stack:** Python ≥3.11, Textual >=8,<9, helixgen[device]>=0.26, pytest + pytest-asyncio, ruff.

## Global Constraints

- **Slots are invisible.** No slot address (`1A`..`8D`) may appear in any UI string, view model, or test fixture name. Ordering is list order only.
- **Only `helixgen_tui/core/` imports `helixgen`.** Enforced by a test (Task 2). No protocol logic, no `.hsp` parsing, no hashing in this repo.
- **Never touch the real `~/.helixgen`** in tests: every test needing state uses the `tmp_home` fixture (sets `HELIXGEN_HOME` and per-area env overrides to tmp paths); a session-scoped autouse guard asserts the real home is untouched.
- **NO device interaction of any kind in tests or manual checks** during this build (the user is playing through the Helix right now). Absolutely never call anything that sets the active tone (`load`/edit-buffer paths). All device behavior is exercised via `FakeDevicePort`.
- **Never `cd` in Bash commands** — the permission classifier jams on it. Use absolute paths and `git -C <dir>`. Applies to every subagent.
- **Git:** remote is named `github` (not origin). Branch from freshly-fetched `github/main`, work in a git worktree under `.claude/worktrees/`, never commit on local `main`. Conventional-ish commit subjects (`feat:`, `test:`, `docs:`, `chore:`).
- **Repo:** `/Users/michael.shea/git/helix/helixgen-tui`. Run everything with `uv run --extra dev` from the worktree (e.g. `uv run --extra dev pytest`). ruff line-length 100.
- **Naming/copy:** app title `helixgen-tui`; tones display as their library logical name (already `$artist - $song - $guitar` shaped); footer statuses `● connected` / `◐ connecting` / `○ offline`.
- Each task lands as its own PR off its own worktree; tests + ruff green before PR; adversarial review before merge (repo rule).

## File Structure (end state)

```
src/helixgen_tui/
  __main__.py        # exists; gains run of the app (keeps --version)
  app.py             # HelixgenTuiApp: modes, bindings, footer wiring
  core/
    __init__.py
    models.py        # frozen view models + OpResult (Task 2)
    ports.py         # LibraryPort/SetlistPort/DevicePort/Core protocols (Task 2)
    real.py          # RealCore factory (Task 3, extended Task 5)
    library.py       # real library/tone adapters (Task 3)
    setlists.py      # real manifest adapters (Task 3)
    device.py        # DeviceService + real device port (Task 5)
  screens/
    __init__.py
    base.py          # LibrarianScreen: tab strip + footer chrome (Task 1)
    library.py       # Task 4 (make-active/sync wired in Task 5)
    setlists.py      # Task 6
    irs.py           # Task 7
    device.py        # Task 8
  widgets/
    __init__.py
    tab_strip.py     # Task 1
    status_footer.py # Task 1 (device state wiring Task 5)
    help_overlay.py  # Task 1
    confirm_modal.py # Task 5 (plan-showing y/n modal)
tests/
  conftest.py        # tmp_home fixture + real-home guard (Task 2/3)
  fake_core.py       # FakeCore/FakeDevicePort (Task 2)
  test_package.py    # exists
  test_shell.py      # Task 1
  test_boundaries.py # Task 2 (import-boundary test)
  core/test_models.py        # Task 2
  core/test_library.py       # Task 3
  core/test_setlists.py      # Task 3
  core/test_device_service.py# Task 5
  screens/test_library.py    # Task 4/5
  screens/test_setlists.py   # Task 6
  screens/test_irs.py        # Task 7
  screens/test_device.py     # Task 8
docs/superpowers/plans/core-api-notes.md  # Task 3 inspection output
```

**Sequencing:** Task 1 → Task 2 → (Task 3 ∥ Task 4) → Task 5 → (Task 6 ∥ Task 7 ∥ Task 8). Parallel tasks use separate worktrees; each rebases on `github/main` before opening its PR.

---

### Task 1: App shell — tabs, footer, help overlay

**Files:**
- Modify: `pyproject.toml` (add `textual>=8,<9` dependency; add `pytest-asyncio>=0.23` to dev extra; add `hxg` console script)
- Modify: `src/helixgen_tui/__main__.py` (run the app; keep `--version`)
- Create: `src/helixgen_tui/app.py`, `src/helixgen_tui/screens/__init__.py`, `src/helixgen_tui/screens/base.py`, `src/helixgen_tui/widgets/__init__.py`, `src/helixgen_tui/widgets/tab_strip.py`, `src/helixgen_tui/widgets/status_footer.py`, `src/helixgen_tui/widgets/help_overlay.py`
- Test: `tests/test_shell.py`

**Interfaces:**
- Consumes: nothing (first code task).
- Produces: `HelixgenTuiApp(App)` constructible with no args in this task (Task 4 changes it to `HelixgenTuiApp(core: Core)`); four mode names `"library"`, `"setlists"`, `"irs"`, `"device"` bound to keys `1`–`4`; `LibrarianScreen(Screen)` base class with `TAB_LABEL: str` and a `body()` compose hook; `StatusFooter` widget with `set_device_text(text: str)`, `set_last_action(text: str)`, and readable `device_text` property; `HelpOverlay(ModalScreen)` opened on `?`, dismissed on `escape`; `q` quits.

- [ ] **Step 1: deps.** In `pyproject.toml` add `"textual>=8,<9"` to `[project] dependencies`, `"pytest-asyncio>=0.23"` to the `dev` extra, and `hxg = "helixgen_tui.__main__:main"` to `[project.scripts]`. Add to `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`. Run `uv lock` then `uv run --extra dev python -c "import textual"` — expect no error.
- [ ] **Step 2: failing shell tests** in `tests/test_shell.py`:

```python
import pytest
from helixgen_tui.app import HelixgenTuiApp

async def test_app_starts_on_library_mode():
    app = HelixgenTuiApp()
    async with app.run_test() as pilot:
        assert app.current_mode == "library"

@pytest.mark.parametrize("key,mode", [("1", "library"), ("2", "setlists"), ("3", "irs"), ("4", "device")])
async def test_number_keys_switch_modes(key, mode):
    app = HelixgenTuiApp()
    async with app.run_test() as pilot:
        await pilot.press(key)
        assert app.current_mode == mode

async def test_question_mark_opens_help_and_escape_closes():
    from helixgen_tui.widgets.help_overlay import HelpOverlay
    app = HelixgenTuiApp()
    async with app.run_test() as pilot:
        await pilot.press("?")
        assert isinstance(app.screen, HelpOverlay)
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpOverlay)

async def test_footer_shows_device_placeholder():
    from helixgen_tui.widgets.status_footer import StatusFooter
    app = HelixgenTuiApp()
    async with app.run_test() as pilot:
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.device_text
```

- [ ] **Step 3:** run `uv run --extra dev pytest tests/test_shell.py -v` — expect FAIL (import errors).
- [ ] **Step 4: implement.** `LibrarianScreen` composes `TabStrip` (top, renders the four labels with the active mode highlighted), the subclass `body()`, and `StatusFooter` (bottom; `device_text` starts `"device: ○ offline"`). `app.py` defines four placeholder screens (subclasses with `TAB_LABEL` and a `Static` body naming the screen), `MODES = {...}`, `BINDINGS` for `1`–`4` (`switch_mode`), `q` → quit, `?` → `push_screen(HelpOverlay())`. `HelpOverlay` is a `ModalScreen` listing bindings; `escape` dismisses. `__main__.py:main()` keeps `--version`, otherwise runs `HelixgenTuiApp().run()` and returns 0 (update `tests/test_package.py` if it asserted the placeholder message).
- [ ] **Step 5:** `uv run --extra dev pytest -v` and `uv run --extra dev ruff check .` — all green.
- [ ] **Step 6: commit** `feat: app shell — tabbed modes, status footer, help overlay`.

### Task 2: View models, ports, FakeCore, boundary test

**Files:**
- Create: `src/helixgen_tui/core/__init__.py`, `src/helixgen_tui/core/models.py`, `src/helixgen_tui/core/ports.py`, `tests/fake_core.py`, `tests/conftest.py`, `tests/test_boundaries.py`, `tests/core/test_models.py`

**Interfaces:**
- Consumes: nothing from Task 1 (pure data layer).
- Produces (exact — later tasks depend on these):

```python
# models.py — all @dataclass(frozen=True, slots=True)
class SyncState(enum.Enum): SYNCED = "synced"; LOCAL_ONLY = "local"; UNKNOWN = "unknown"
class ToneVM:      name: str; tone_id: str; guitar: str | None; description: str | None; sync: SyncState; setlists: tuple[str, ...]
class SetlistVM:   name: str; sync_enabled: bool; tones: tuple[str, ...]   # tone names, in order
class IrVM:        name: str; pack: str | None; irhash: str | None; on_device: bool | None  # None = unknown/offline
class DeviceStateVM: status: str; model: str | None; address: str | None; active_tone: str | None; detail: str
                    # status ∈ {"offline", "connecting", "connected"}
class MutationPlan: title: str; lines: tuple[str, ...]                     # what a confirm modal displays
class OpResult:    ok: bool; message: str

# ports.py — typing.Protocol, all sync (DeviceService threads them later)
class LibraryPort:  def list_tones(self) -> list[ToneVM]; def get_tone(self, tone_id: str) -> ToneVM | None
class SetlistPort:  def list_setlists(self) -> list[SetlistVM]
                    def add_tone(self, setlist: str, tone_id: str) -> OpResult
                    def remove_tone(self, setlist: str, tone_id: str) -> OpResult
                    def move_tone(self, setlist: str, tone_id: str, delta: int) -> OpResult
class DevicePort:   def probe(self) -> DeviceStateVM               # raises DeviceUnreachable on failure
                    def list_device_irs(self) -> list[IrVM]
                    def make_active(self, tone_id: str) -> OpResult
                    def sync_tone(self, tone_id: str) -> OpResult
                    def sync_setlist(self, name: str, gc: bool) -> OpResult
                    def plan_sync_all(self, gc: bool) -> MutationPlan
                    def sync_all(self, gc: bool) -> OpResult
                    def plan_delete_tone(self, tone_id: str) -> MutationPlan
                    def delete_tone(self, tone_id: str) -> OpResult
                    def push_ir(self, ir_name: str) -> OpResult
                    def plan_delete_ir(self, ir_name: str) -> MutationPlan
                    def delete_ir(self, ir_name: str) -> OpResult
                    def plan_prune_irs(self) -> MutationPlan
                    def prune_irs(self) -> OpResult
                    def rename_ir(self, ir_name: str, new_name: str) -> OpResult
                    def info(self) -> dict[str, str]
                    def backup(self) -> OpResult
                    def plan_restore(self, file: str) -> MutationPlan
                    def restore(self, file: str) -> OpResult
                    def lock_status(self) -> list[str]
class DeviceUnreachable(Exception): ...
class Core:         library: LibraryPort; setlists: SetlistPort; device: DevicePort
                    def list_local_irs(self) -> list[IrVM]
```

- `tests/fake_core.py` produces `FakeCore(tones=[...], setlists=[...], local_irs=[...], device=FakeDevicePort(...))` implementing `Core` (all args optional, empty defaults). `FakeDevicePort(state=DeviceStateVM(...), fail_next: bool = False)` records every mutation in `self.calls: list[tuple[str, tuple]]`, returns scripted `OpResult`s (default `OpResult(True, "<verb> ok")`), and raises `DeviceUnreachable` on the next call when `fail_next` — screens/tests script offline, flake, and contention with it.
- `tests/conftest.py` produces the `tmp_home` fixture (monkeypatches `HELIXGEN_HOME`, `HELIXGEN_LIBRARY`, `HELIXGEN_SETLISTS`, `HELIXGEN_CACHE`, `HELIXGEN_PREFS`, `HELIXGEN_LOCKS`, `HELIXGEN_IRS` to tmp_path subdirs) and an autouse session guard fixture that snapshots `~/.helixgen`'s file list+mtimes and asserts unchanged at session end.

- [ ] **Step 1: failing tests** — `tests/core/test_models.py` (view models are frozen: assigning raises `FrozenInstanceError`; `SyncState` values round-trip), `tests/test_boundaries.py`:

```python
import pathlib, re
SRC = pathlib.Path(__file__).parent.parent / "src" / "helixgen_tui"
def test_only_core_imports_helixgen():
    offenders = [p for p in SRC.rglob("*.py")
                 if "core" not in p.parts
                 and re.search(r"^\s*(import|from)\s+helixgen\b", p.read_text(), re.M)]
    assert offenders == []
```

plus a FakeCore self-test (mutations append to `calls`; `fail_next` raises `DeviceUnreachable` once then clears).
- [ ] **Step 2:** run — expect FAIL (modules missing).
- [ ] **Step 3:** implement `models.py`, `ports.py`, `fake_core.py`, `conftest.py` exactly as specified above.
- [ ] **Step 4:** `uv run --extra dev pytest -v` + ruff — green.
- [ ] **Step 5: commit** `feat: core view models, ports, FakeCore, import-boundary guard`.

### Task 3: Real library + setlist adapters (temp-home tests)

**Files:**
- Create: `docs/superpowers/plans/core-api-notes.md`, `src/helixgen_tui/core/library.py`, `src/helixgen_tui/core/setlists.py`, `src/helixgen_tui/core/real.py`, `tests/core/test_library.py`, `tests/core/test_setlists.py`

**Interfaces:**
- Consumes: Task 2's models/ports; the installed `helixgen` package.
- Produces: `RealLibrary(LibraryPort)`, `RealSetlists(SetlistPort)`, and `build_core() -> Core` in `real.py` (Task 5 extends it with the real device port; until then `Core.device` is a `NullDevicePort` whose `probe()` raises `DeviceUnreachable("no device configured")` and whose other methods return `OpResult(ok=False, message="device support arrives in a later task")`).

- [ ] **Step 1: inspect, don't guess.** Establish the EXACT `helixgen` functions for: listing tone metadata, guitars, local IRs + `mapping.json`, reading/writing the setlist manifest (v3), and how recorded install/sync state is stored (`devices/<serial>.json` observed placement). Prefer `uv run --extra dev python -m pydoc helixgen.tone_meta` (and siblings: `guitars`, `ir_meta`, `home`, `preferences`, module list via `pkgutil.iter_modules`) — do NOT source-dive for behavior questions; where the Python surface is genuinely undocumented, note the risk. Record findings as signatures in `docs/superpowers/plans/core-api-notes.md`. If recorded sync state is not derivable offline, map every tone to `SyncState.UNKNOWN` and note it — do NOT invent drift detection (spec allows this).
- [ ] **Step 2: failing tests.** In `tests/core/test_library.py` (using `tmp_home`): seed the temp home *through core's own APIs* (per the notes doc — e.g. write tone metadata + `.hsp` registration via `helixgen.tone_meta`'s writers, NOT hand-built directory trees); assert `RealLibrary().list_tones()` returns one `ToneVM` with the logical name and the derivable `SyncState`. In `tests/core/test_setlists.py`: create a manifest with one setlist × two tones via core's manifest API; assert `list_setlists()` order matches manifest order; `move_tone(name, tone_id, -1)` swaps order and persists (fresh adapter re-read proves it); `add_tone`/`remove_tone` round-trip; unknown setlist/tone names return `OpResult(ok=False, ...)` — never raise.
- [ ] **Step 3:** run — FAIL (modules missing).
- [ ] **Step 4:** implement the adapters per the notes doc; catch core exceptions at the adapter boundary and convert to `OpResult(ok=False, message=str(exc))`.
- [ ] **Step 5:** full suite + ruff green.
- [ ] **Step 6: commit** `feat: real library/setlist adapters over helixgen (+ core API notes)`.

### Task 4: Library screen (read-only browse)

**Files:**
- Create: `src/helixgen_tui/screens/library.py`, `tests/screens/test_library.py`
- Modify: `src/helixgen_tui/app.py` (accept `core: Core`; replace the library placeholder), `src/helixgen_tui/__main__.py` (pass `build_core()`)

**Interfaces:**
- Consumes: `Core`/`LibraryPort`, `ToneVM`, `LibrarianScreen`, `FakeCore`.
- Produces: `HelixgenTuiApp(core: Core)` (all later tasks construct it this way; shell tests from Task 1 switch to `HelixgenTuiApp(FakeCore())`); `LibraryScreen` with a `DataTable` (columns: Tone, Guitar, Sync), `enter` opens `ToneDetailModal` (name, guitar, setlists, description), `r` refreshes from `core.library`, `/` focuses a filter `Input` that narrows rows by substring, `escape` clears it.

- [ ] **Step 1: failing Pilot tests** — app built with a 3-tone `FakeCore`: rows appear with names and sync glyphs (`✓`/`○`/`?`); `enter` opens detail modal showing the tone's setlist names; `escape` closes; `/`+typed text filters rows; `r` picks up a tone appended to the FakeCore's tone list after launch. Include one assertion that no rendered text matches `r"\b[1-8][A-D]\b"` (slots invisible).
- [ ] **Step 2:** run — FAIL. **Step 3:** implement (screen calls `core.library.list_tones()` on mount and on `r`; table rebuild is a plain sync method — local reads are cheap per spec).
- [ ] **Step 4:** suite + ruff green. **Step 5: commit** `feat: library screen — browse, detail, filter`.

### Task 5: DeviceService, footer wiring, make-active + sync-tone, confirm modal

**Files:**
- Create: `src/helixgen_tui/core/device.py`, `src/helixgen_tui/widgets/confirm_modal.py`, `tests/core/test_device_service.py`
- Modify: `src/helixgen_tui/core/real.py` (real `DevicePort` over helixgen's device client — extend `core-api-notes.md` first, same inspect-don't-guess rule; **the real port's `make_active` is the only code that may reference core's load verb, and nothing in this build may invoke it against real hardware**), `src/helixgen_tui/app.py` (own a `DeviceService`, route updates to `StatusFooter`), `src/helixgen_tui/screens/library.py` (`a` make-active, `s` sync-tone), `tests/screens/test_library.py`

**Interfaces:**
- Consumes: `DevicePort`, `DeviceStateVM`, `MutationPlan`, `OpResult`, shell + library screen.
- Produces:

```python
class DeviceService:
    def __init__(self, port: DevicePort, on_state: Callable[[DeviceStateVM], None],
                 poll_interval: float = 15.0, timeout: float = 5.0,
                 spawn: Callable[[Callable[[], None]], None] | None = None): ...
    # spawn defaults to a thread-worker runner; tests inject a synchronous spawn.
    def start(self) -> None            # begin background probe loop
    def retry_now(self) -> None
    @property
    def state(self) -> DeviceStateVM
    def run(self, label: str, fn: Callable[[], OpResult],
            done: Callable[[OpResult], None]) -> None
    # runs fn via spawn with timeout; DeviceUnreachable/timeout → OpResult(ok=False, ...);
    # flips state offline on unreachable; offline short-circuits without calling fn.
ConfirmModal(ModalScreen[bool])       # ConfirmModal(plan: MutationPlan); y→True, n/escape→False
```

- App wires `on_state` → footer `set_device_text` and `OpResult` messages → `set_last_action`.

- [ ] **Step 1: failing service tests** (pure Python — inject synchronous `spawn`): probe success → `connected` state callback; probe raising `DeviceUnreachable` → `offline`; `run()` while offline short-circuits to `OpResult(ok=False, message="device offline")` without touching the port; port raising `DeviceUnreachable` mid-`run` flips state offline; a `fn` exceeding `timeout` (test with `timeout=0.01` and a sleeping fn under a real thread spawn) yields `ok=False` with `"timed out"` in the message.
- [ ] **Step 2: failing screen tests:** with connected `FakeDevicePort`, `a` on a `SYNCED` tone puts `("make_active", (tone_id,))` in `port.calls` and the footer shows the result message; `a` while offline does NOT call the port and the footer explains why; `a` on a `LOCAL_ONLY` tone opens `ConfirmModal` whose lines mention installing, `y` → `sync_tone` then `make_active`, `n` → no calls; `s` calls `sync_tone`. **Never any real device in these tests.**
- [ ] **Step 3:** run — FAIL. **Step 4:** implement service, modal, bindings, and the real port in `real.py` per the extended notes doc.
- [ ] **Step 5:** suite + ruff. **Step 6: commit** `feat: DeviceService, offline-first footer, make-active/sync, confirm modal`.

### Task 6: Setlists screen

**Files:**
- Create: `src/helixgen_tui/screens/setlists.py`, `tests/screens/test_setlists.py`; Modify: `src/helixgen_tui/app.py` (replace placeholder)

**Interfaces:**
- Consumes: `SetlistPort`, `DeviceService`, `ConfirmModal`, `FakeCore`.
- Produces: `SetlistsScreen`: left pane setlist list (name + sync-enabled glyph), right pane the selected setlist's tones in order; `a` add-tone picker (library tones not already in the setlist), `d` remove selected tone, `J`/`K` move selected tone down/up (`move_tone` ±1), `S` sync selected setlist (instant tier), `A` sync-all via `ConfirmModal(plan_sync_all(gc=False))`.

- [ ] **Step 1: failing Pilot tests:** panes render FakeCore setlists in manifest order; `J` calls `move_tone(name, tone_id, +1)` and re-renders the new order; `d` removes; `S` calls `sync_setlist` when connected and refuses with a footer reason offline; `A` shows the plan lines from `plan_sync_all` and `y` calls `sync_all`; an `OpResult(ok=False, message=...)` sync surfaces its message in the footer. No slot-address strings rendered.
- [ ] **Step 2:** FAIL → **Step 3:** implement → **Step 4:** green + ruff → **Step 5: commit** `feat: setlists screen — membership, ordering, sync`.

### Task 7: IRs screen

**Files:**
- Create: `src/helixgen_tui/screens/irs.py`, `tests/screens/test_irs.py`; Modify: `src/helixgen_tui/app.py`

**Interfaces:**
- Consumes: `Core.list_local_irs()`, `DevicePort` IR verbs, `ConfirmModal`, `FakeCore`.
- Produces: `IrsScreen`: left pane local IRs (name, pack, short hash), right pane device IRs or an `unavailable — device offline` placeholder; `p` push selected local IR (instant tier), `R` rename device IR (inline `Input` prompt), `d` delete device IR via `ConfirmModal(plan_delete_ir)`, `P` prune via `ConfirmModal(plan_prune_irs)`.

- [ ] **Step 1: failing Pilot tests:** local pane lists FakeCore IRs while offline; device pane shows the offline placeholder, and rows once the fake state is connected; `p` calls `push_ir`; `d` shows the plan, `y` deletes / `n` doesn't; `P` renders `MutationPlan.lines` verbatim in the modal.
- [ ] **Step 2:** FAIL → **Step 3:** implement → **Step 4:** green + ruff → **Step 5: commit** `feat: IRs screen — local/device panes, push, delete, prune`.

### Task 8: Device screen + release polish

**Files:**
- Create: `src/helixgen_tui/screens/device.py`, `tests/screens/test_device.py`; Modify: `src/helixgen_tui/app.py`, `src/helixgen_tui/widgets/help_overlay.py` (full keymap), `README.md` (usage section; replace "design phase" status), `pyproject.toml` (version `0.1.0`, classifier → `Development Status :: 3 - Alpha`), `docs/BACKLOG.md` (add the deferred live-smoke-suite entry; mark #1 fully done)

**Interfaces:**
- Consumes: everything prior.
- Produces: `DeviceScreen`: info table (`device.info()` when connected), active-tone line, `b` backup (instant tier — read-only, shows result message), `t` restore via path `Input` + `ConfirmModal(plan_restore)`, `l` lock status lines, `r` retry-connect (`DeviceService.retry_now`).

- [ ] **Step 1: failing Pilot tests:** offline → info pane placeholder and `b` refused with reason; connected FakeDevicePort → info rows render, `b` calls `backup`, restore flow shows plan then calls `restore` on `y`; lock status lines render.
- [ ] **Step 2:** FAIL → **Step 3:** implement → **Step 4:** suite + ruff green.
- [ ] **Step 5:** README + help overlay + version bump + backlog updates; run the full suite once more.
- [ ] **Step 6: commit** `feat: device screen; docs, backlog, 0.1.0`.

## Release (after all PRs merge)

Task 8's merge carries the 0.1.0 bump: tag `v0.1.0` on `main` fires `publish.yml` (releases are preapproved per workspace standing approvals). Then update the tri-repo `BACKLOG.md` (#29/#60 → shipped ledger).

## Self-Review notes

- Spec coverage: shell/D2 → Task 1; adapter boundary/D5 → Tasks 2–3; Library browse → 4; offline-first/D3 + tiered confirm/D4 + DeviceService → 5; Setlists → 6; IRs → 7; Device screen → 8; testing/D6 layers → conftest guard + FakeCore (Task 2/3) + Pilot throughout; packaging delta (textual pin, `hxg` alias) → Task 1; live smoke suite → deferred per spec (backlog entry added in Task 8).
- The real `DevicePort` verbs beyond construction cannot be integration-tested in this build (device off-limits while the user plays); they are thin per-verb delegations documented in `core-api-notes.md` and exercised by the deferred live smoke suite post-v1.

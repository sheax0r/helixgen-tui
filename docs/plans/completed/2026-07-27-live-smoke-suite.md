# Plan: Live smoke suite for `RealDevicePort` (`HELIXGEN_TUI_LIVE=1`)

## Context

Implements `docs/BACKLOG.md #5` (deferred per spec D6). Every device test in the
v1 build is `FakeDevicePort`-driven; `RealDevicePort`
(`src/helixgen_tui/core/real.py`) is **signature-verified only** — its per-verb
delegations to helixgen's device layer (`HelixClient`, `setlist_sync`,
`maintenance`, `backup`, `locks`) have never been run against hardware. A
signature match cannot catch a renamed keyword, a changed return shape, or a
verb that raises where the port expects a value — exactly the breakage this
suite exists to find, and exactly what will bite a user the first time they
press a device key.

Deliverable: an opt-in, env-gated live suite that exercises the real port's
verbs against an actual Helix Stadium, plus one hardware run of it with results
recorded. Findings that are helixgen-core bugs get filed in the **core** backlog
(this repo never patches engine behavior); findings that are TUI-side get fixed
here under TDD.

Repo rules apply: TDD, `helixgen_tui.core` stays the only helixgen importer,
offline-first (the suite must not change how the app behaves with no device),
deferred work filed as a numbered `docs/BACKLOG.md` entry.

### Hardware/environment facts for this run

- A Stadium XL (fw 1.3.2 build 1340) is reachable on the LAN and persisted in
  helixgen's device record; `helixgen device info` works with no `--ip`. If it
  is NOT reachable, STOP — do not stub, fake, or skip your way to a green run.
  Leave the task unchecked and report.
- The installed engine is `helixgen` 0.30.0 (uv tool + importable). Live tests
  need `pyzmq` available to the interpreter running pytest.
- **Device locks:** helixgen's mutating verbs auto-acquire advisory leases. Do
  not hold a long session lease across the pytest run unless the suite itself
  takes and passes a `HELIXGEN_LOCK_TOKEN`; pick one strategy and document it in
  the suite's conftest docstring.
- Device writes are preapproved for test runs. Confine every write to
  `HGTEST`-prefixed artifacts, take an upfront `device backup` to scratch, tear
  everything down in finalizers (including on failure), and never leave the
  device in a broken state.

### Task 1: Suite skeleton, gating, and safety fixtures

Model the safety fixtures on helixgen-core's `tests/live/conftest.py` (read it —
it is the reference implementation of this safety model).

- [x] Add `tests/live/` with a `conftest.py` whose module docstring states the
      full safety model, the gating, and any deliberately excluded verb (and why)
- [x] Gate everything behind `HELIXGEN_TUI_LIVE=1` **plus** a cheap TCP
      reachability probe of the device's ZMQ ROUTER port (the Stadium ignores
      ICMP, so ping is useless). Without both, every test skips — the default
      `pytest` run and CI must stay green and offline
- [x] Register a `live` marker in `pyproject.toml` and keep it out of the default
      `testpaths` run, or make the gate a hard skip — whichever keeps a plain
      `pytest` invocation on a dev machine with a device on the LAN from firing
      device writes by accident. State the choice in the docstring
- [x] Redirect ALL local helixgen state to a session scratch dir
      (`HELIXGEN_SETLISTS`, `HELIXGEN_IRS`, `HELIXGEN_IRHASH_CACHE`,
      `HELIXGEN_PREFS`, device backups); leave `HELIXGEN_LIBRARY` pointing at the
      real block library read-only, skipping if it is absent
- [x] Take an upfront `device backup` (to scratch) before the first device test
- [x] Capture device state (presets / setlists / IRs) before the first device
      test and re-capture at session teardown; **fail the session** if the
      normalized state changed. Document known blind spots honestly
- [x] Verify at teardown that the user's real `~/.helixgen` files are unchanged

### Task 2: Read-only verb coverage

- [x] Cover the read/status verbs against hardware: `probe`, `info`,
      `list_device_irs`, `lock_status`, and the plan-only verbs
      (`plan_sync_all`, `plan_delete_tone`, `plan_delete_ir`, `plan_prune_irs`,
      `plan_restore`) — asserting the **shapes the TUI consumes**
      (`DeviceStateVM`, `IrVM`, `MutationPlan`, `OpResult`), not just non-crash
- [x] Cover the offline-first hinge on real hardware conditions: with no device
      configured, `probe` raises `DeviceUnreachable` immediately and without a
      socket; with a device configured but unreachable (e.g. a bogus port), the
      failure maps to `DeviceUnreachable` rather than escaping raw
- [x] Record any mismatch between what `RealDevicePort` expects and what the
      installed helixgen 0.30.0 actually returns. Engine-side gaps go to the
      **core** backlog (`helixgen-core/docs/BACKLOG.md`) — note them in this
      repo's findings doc and do not patch engine behavior here
      (2026-07-27 hardware run: 13/13 passed against Stadium XL fw 1.3.2 —
      NO mismatches found in the read/status/plan verbs; nothing to file)

### Task 3: Mutating verb coverage, `HGTEST`-scoped

- [x] Cover the mutating verbs with `HGTEST`-prefixed artifacts and finalizer
      teardown: `sync_tone`, `sync_setlist`, `sync_all` (scoped so it cannot
      touch untracked device presets — sync is a managed-set mirror; confirm that
      property holds in the assertions), `delete_tone`, `push_ir`, `rename_ir`,
      `delete_ir`, `prune_irs`, `backup`
      (`sync_all` covered with `gc=False` only — the GC phase would delete real
      unreferenced pool presets invisibly to the state guard; `prune_irs` gated
      on the engine's dry-run plan so it only ever executes over its own HGTEST
      orphan — both stated in the conftest docstring)
- [x] `make_active` changes the player's ACTIVE tone by design: cover it, but
      capture the active preset first and restore it at teardown
- [x] **Exclude `restore`** from live writes (it overwrites an existing preset;
      core's live suite excludes it for the same reason) and assert only its
      unsupported/plan paths. State the exclusion in the conftest docstring
- [x] Assert `OpResult.ok` **and** the message text the TUI footer shows — a verb
      that fails soft with `ok=False` is exactly the silent breakage this suite
      exists to catch

### Task 4: Run it on hardware and act on the results

- [x] Run the suite against the device and record the verbatim result
      (2026-07-27, Stadium XL fw 1.3.2 b1340 — first full run: `8 failed,
      13 passed, 1 error in 223.62s` — all failures a mid-run device network
      drop (Stadium flakiness, port 2002 stopped answering ~1 min; device
      clean on recovery, no HGTEST leftovers, no stale locks). Second run:
      `2 failed, 19 passed in 396.54s` — both IR tests, real defects below.
      Final run: `20 passed, 1 skipped in 371.55s` — the skip is the prune
      test's own safety gate: the device has real non-HGTEST orphan IRs, so
      it refuses to execute a real prune over them, by design)
- [x] Fix TUI-side defects under TDD (offline failing test first wherever the
      defect is reachable with `FakeDevicePort`; the live test is the backstop,
      not the primary regression net)
      (one found: `RealDevicePort.push_ir` treated every engine outcome except
      `upload_error` as success — soft failures (`upload_failed`,
      `not_yet_registered`, `hash_mismatch`, `not_found_locally`) reported
      `ok=True`. Not reachable via `FakeDevicePort` (defect is in the real
      port's engine-result mapping) — offline failing test added directly
      against the port with the upload monkeypatched:
      `test_push_ir_engine_soft_failure_flips_ok_false`. Fix: trust the
      engine's per-hash `ok` and surface its `note` in the footer message)
- [x] File engine-side defects as numbered entries in the **core** backlog, and
      list them in this repo's `docs/BACKLOG.md` #5 close-out note so the
      cross-repo dependency is visible
      (one engine gap found, nothing to file: on helixgen ≤0.30 a pushed IR
      is registered (hash→path resolves, `/addContent` seen) but NEVER
      appears in the -11 `list-irs` listing — reproduced by hand on hardware.
      Already fixed upstream as core #38 in 0.31.0 (hardware-validated
      2026-07-27, listing-cache nudge in `push_ir`). Action here: engine pin
      bumped to `helixgen[device]>=0.31`, lock upgraded to 0.32.0; Task 5's
      close-out note will reference core #38)
- [x] Re-run until the suite passes or every remaining failure is an explicitly
      filed engine gap

### Task 5: Docs and backlog

- [x] Write `docs/superpowers/specs/2026-07-27-live-smoke-suite.md`: what the
      suite covers, the safety model, what is deliberately excluded, the hardware
      run's verbatim results, and every defect found
- [x] `docs/BACKLOG.md`: close **#5** with a one-line note pointing at the
      findings doc — or rewrite it to say precisely what remains
      (closed with the ✅ note: hardware-validated, push_ir fix, core #38
      reference, findings-doc pointer)
- [x] `CLAUDE.md`: document how to run the live suite (env vars, gating,
      safety posture) next to the existing test guidance
- [x] Confirm the default offline suite is still green and still skips
      everything under `tests/live/`
      (2026-07-27: `274 passed, 21 skipped` — all 21 skips are `tests/live/`
      opt-in gates; `ruff check .` clean)

## Validation Commands

Run from the repo root:

- `python3 -m pytest` — full offline suite (must stay green and must skip the
  new live suite entirely)
- `ruff check .` — lint

Live (REQUIRED for this plan — a green offline suite alone does NOT satisfy
Tasks 2-4):

- `HELIXGEN_TUI_LIVE=1 python3 -m pytest tests/live -q`

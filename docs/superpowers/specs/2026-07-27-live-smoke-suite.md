# Live smoke suite for `RealDevicePort` (backlog #5, spec D6)

2026-07-27. Closes `docs/BACKLOG.md` #5. Plan:
`docs/plans/completed/2026-07-27-live-smoke-suite.md`.

## Why

Every device test in the v1 build drives `FakeDevicePort`; `RealDevicePort`
(`src/helixgen_tui/core/real.py`) was signature-verified only — its per-verb
delegations to helixgen's device layer had never run against hardware. A
signature match cannot catch a renamed keyword, a changed return shape, or a
verb that raises where the port expects a value. This suite runs the real
port, in-process, against a real Helix Stadium, and asserts the shapes the TUI
consumes (`DeviceStateVM`, `IrVM`, `MutationPlan`, `OpResult`) — including the
`OpResult.ok` flag and footer message text, because a verb that fails soft
with `ok=True` is exactly the silent breakage the suite exists to catch. That
assertion found the one TUI defect (below).

## What it covers

`tests/live/` — three modules behind a session safety chain
(`tests/live/conftest.py`, whose module docstring is the authoritative
statement of the safety model):

- `test_gate.py` — the scratch env redirect actually took effect; the full
  safety chain (probe → upfront backup → state guard) stands up.
- `test_read_verbs.py` — `probe`, `info`, `list_device_irs` (cross-checked
  against the engine CLI's listing), `lock_status` (sees the suite's own
  session lease), the plan-only verbs (`plan_sync_all`, `plan_delete_tone`,
  `plan_delete_ir`, `plan_prune_irs`, `plan_restore`), and the offline-first
  hinge on real hardware conditions: unconfigured `probe` raises
  `DeviceUnreachable` without opening a socket; a configured-but-unreachable
  device (bogus port) maps to `DeviceUnreachable` rather than escaping raw.
- `test_mutating_verbs.py` — `HGTEST`-prefixed artifacts with finalizer
  teardown: the full sync lifecycle (`sync_tone`, `sync_setlist`,
  `sync_all(gc=False)`, `delete_tone` soft-fail path) asserting sync stays a
  managed-set mirror that never touches untracked device presets; the IR
  roundtrip (`push_ir`, `rename_ir`, `delete_ir`); `prune_irs` gated on the
  engine's dry-run plan; `make_active` with capture-and-restore of the active
  preset; `backup`; and the unsupported paths (`delete_tone` unwired,
  `restore` write-excluded).

## Gating and safety model

Summary (the conftest docstring is normative):

- **Opt-in:** everything hard-skips at collection unless
  `HELIXGEN_TUI_LIVE=1`; device-backed tests additionally need a TCP-connect
  probe of the Stadium's ZMQ ROUTER port 2002 to succeed (the Stadium ignores
  ICMP). `tests/live` stays inside default `testpaths` so the skip is visible
  in `-ra` output; a `live` marker is registered for `-m live` selection.
  Default `pytest` and CI stay green, offline, and incapable of device writes.
- **Scratch redirect:** all local helixgen state (`HELIXGEN_HOME`, setlists,
  device slots, IRs, irhash cache, backups, prefs) points at a session
  scratch dir; only `HELIXGEN_LIBRARY` stays real, read-only (suite skips
  without it). The device IP is resolved before the redirect and pinned via
  `HELIXGEN_HELIX_IP`.
- **Locks:** the suite holds the real machine-local `all` advisory lease for
  the whole run (label `tui-live-suite`) and passes a per-run
  `HELIXGEN_LOCK_TOKEN` so its own verbs pass through it. `HELIXGEN_LOCKS`
  deliberately stays real — the lease exists to exclude other helixgen
  processes on the machine.
- **State guard:** upfront `device backup` to scratch; device state (user
  presets / setlists / IRs) captured before the first device test and
  re-captured at teardown — the session itself fails if the normalized state
  changed. Stale `HGTEST` leftovers from a crashed run are swept before the
  baseline capture. `device list --json` defaults to `--setlist user`, which
  IS the preset pool (cid -2, where every user preset lives), so pool leaks
  are covered by the diff. Known blind spot, stated honestly: the active edit
  buffer isn't diffed (unsaved pre-run edits
  are discarded by `make_active` restore, by design). The repo-wide guard in
  `tests/conftest.py` verifies the user's real `~/.helixgen` (minus `locks/`)
  is untouched.
- **HGTEST discipline:** every artifact the suite creates carries the
  `HGTEST` prefix; teardown helpers refuse to touch anything without it.

## Deliberately excluded

- **`restore`** — overwrites an existing preset's content in place; no
  `HGTEST`-scoped way to exercise it (core's live suite excludes it for the
  same reason). Only its unsupported/plan paths are asserted.
- **`sync_all(gc=True)`** — the GC phase deletes device pool presets the
  manifest doesn't reference; against the suite's scratch manifest that means
  every real pool preset. The state guard would report the damage, but only
  after it happened, and no TUI surface passes `gc=True` (`screens/setlists.py`
  passes `False` at every call site). Covered with `gc=False` only. `prune_irs` — a
  real deletion too — stays in, but executes only when the engine's dry-run
  plan shows the sole orphan is the test's own `HGTEST` IR; on a device with
  real orphan IRs it skips itself.

## Hardware run (2026-07-27, Stadium XL fw 1.3.2 build 1340)

- First full run: `8 failed, 13 passed, 1 error in 223.62s` — all failures a
  mid-run device network drop (Stadium flakiness; port 2002 stopped answering
  for ~1 min). Device clean on recovery: no `HGTEST` leftovers, no stale
  locks.
- Second run: `2 failed, 19 passed in 396.54s` — both IR tests; real defects,
  below.
- Final run (after fixes): `20 passed, 1 skipped in 371.55s` — the skip is
  the prune test's own safety gate (the device has real non-HGTEST orphan
  IRs, so it refuses to execute a real prune over them, by design).

## Defects found

- **TUI: `RealDevicePort.push_ir` swallowed engine soft failures.** It
  treated every engine outcome except `upload_error` as success — soft
  failures (`upload_failed`, `not_yet_registered`, `hash_mismatch`,
  `not_found_locally`) reported `ok=True` to the footer. Not reachable via
  `FakeDevicePort` (the defect is in the real port's engine-result mapping),
  so the offline regression test monkeypatches the upload:
  `tests/core/test_real_core.py::test_push_ir_engine_soft_failure_flips_ok_false`.
  Fix: trust the engine's per-hash `ok` and surface its `note` in the footer
  message.
- **Engine (helixgen ≤0.30): pushed IR never appears in the -11 `list-irs`
  listing** despite being registered (hash→path resolves, `/addContent`
  observed) — reproduced by hand on hardware. Already fixed upstream as
  **core #38** in 0.31.0 (listing-cache nudge in `push_ir`,
  hardware-validated 2026-07-27), so nothing new was filed. Action here: the
  engine pin was bumped to `helixgen[device]>=0.31` (lock at 0.32.0).

### Found in adversarial review of the suite itself (2026-07-27)

The suite's plan-verb tests asserted `MutationPlan` *shape* only, which three
IR verbs satisfied while lying about (or discarding) the engine's report:

- **`plan_prune_irs` read report keys the engine has never emitted**
  (`prunable`/`prune`; the engine returns candidates under `orphans`). The
  plan therefore always rendered "(no unreferenced device IRs to prune)" —
  and that placeholder is what the destructive `ConfirmModal` showed before
  `prune_irs()` went on to delete every orphan for real. The live run's own
  log proves the skew was reproducible: the prune test skipped *because the
  device had real non-HGTEST orphans* at the same moment the plan reported
  none. Fixed, plus: the plan now surfaces the engine's `warnings`, a
  planning abort is reported as itself instead of as "device unreachable",
  `test_plan_prune_irs_matches_engine_cli` cross-checks the plan against
  `device ir-prune --json` (the pattern `test_list_device_irs_matches_engine_cli`
  already used), and offline unit tests pin the report shape.
- **`prune_irs` and `delete_ir` hardcoded `ok=True`**, discarding reports in
  which the engine records per-IR delete refusals (`errors`, `ok=False`) and
  never raises — the same defect class as the `push_ir` fix above. Both now
  fold the report; `prune_irs` reports the deletion count.

Suite hardening from the same review: the stale-`HGTEST` sweep now fails the
session if a delete fails (a surviving leftover would be absorbed into the
state baseline, so teardown would then match and report a clean device); the
backup test compares mtimes instead of a file count the upfront-backup fixture
already satisfied; `_persisted_device_ip` can no longer raise at collection
time on a malformed device record (it ran on every default offline run); the
state-diff normalizer no longer risks a `TypeError` on rows with missing keys;
`_live_env` fails fast below helixgen 0.31 instead of presenting core #38 as a
TUI regression; the session lease is no longer taken against a fabricated
`no-device` address and its TTL is sized to the run (30 min, not 2 h).

**Correction to the safety model as first documented:** the state guard was
described as blind to the preset pool. It is not — `device list --json`
defaults to `--setlist user`, which *is* the pool (cid -2). The `gc=True`
exclusion still stands, on the honest reason: the guard would only report the
damage after the presets were already deleted, and no TUI surface passes
`gc=True`.

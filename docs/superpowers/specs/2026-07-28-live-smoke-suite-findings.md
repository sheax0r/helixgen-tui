# Live smoke suite (#5) — close-out findings

Hardware: Helix Stadium XL, fw 1.3.2 (build 1340), at 192.168.4.84.
Engine: `helixgen` 0.32.0. Plan:
`docs/plans/2026-07-28-live-smoke-closeout.md`. Design:
`docs/superpowers/specs/2026-07-28-live-smoke-suite-closeout-design.md`.

## Task 1 — hardware re-run

The suite's only previous hardware run predated twelve rounds of review edits,
several of which touched the port's device-unreachable classification. This is
its first end-to-end run in final form.

```
HELIXGEN_TUI_LIVE=1 uv run pytest tests/live -q
20 passed, 1 skipped in 556.76s (0:09:16)
```

**The one skip is the triage rule working, not a gap.** The prune-execute test
refused to run a real prune because the device carries five non-`HGTEST`
orphan IRs, and it named them rather than passing quietly:

```
SKIPPED tests/live/test_mutating_verbs.py:409: device has non-HGTEST prunable
IRs (or verification warnings) — not executing a real prune over them:
orphans=[... 'YA FTWN 212 D120 Mix 05', 'YA DXVB 112 Mix 09',
'YA KW 412 M25 Mix 08', 'YA MRSH 412 T75 Mix FRED',
'YA VX30 212 BLU Mix 08'] warnings=[]
```

That is triage rule (c), environment shortfall → skip with a stated reason.
No rule (a) TUI defects and no rule (b) engine defects surfaced: nothing
needed fixing or filing.

**Device left clean**, verified after the run: 0 `HGTEST` IRs, 0 `HGTEST`
setlists, no held leases, working tree clean.

## Task 2 — backlog #26 confirmed

Measured with the service driven exactly as the app drives it (state
`connected`, real daemon-thread spawn):

| call | wall clock |
|---|---|
| `port.probe()` | 2.97 s |
| `port.plan_prune_irs()` | **51.42 s** |
| `port.plan_sync_all(gc=False)` | 0.00 s (local manifest only — no device I/O) |
| `plan_prune_irs` through `DeviceService.query` | returns at **5.01 s**, `ok=False`, `message='Prune: timed out'` |

**Verdict: CONFIRMED.** The app's Prune preview reports a timeout every time
on this device and never appears — a 10× margin over the 5 s join, so no
plausible device is fast enough. Sync *planning* is unaffected (no device
I/O); the sync *execute* path shares the join and is unmeasured here.

An invalid first attempt is worth recording: driving `DeviceService.query`
without first bringing the service online returned `device offline` in 0.00 s,
because both `run` and `query` short-circuit on cached offline state without
calling the port. The measurement needs `retry_now()` first.

The timeout is a **join, not a cancel** — `_call_guarded` starts a daemon
thread and stops waiting, so a mutating verb slower than the join reports
failure and completes anyway: a false failure over a write that lands. Pinned
by `tests/core/test_device_service.py::test_run_timeout_reports_failure_while_the_write_still_lands`,
which the live suite structurally cannot provide (every live test drives
`real_port` directly, never the service).

**The fix is deliberately not in this change.** It is a UX decision (per-op
timeouts versus an in-flight indicator), and deciding it inside a close-out is
the failure mode this plan exists to avoid.

## What the suite was worth

Building it found four defects in code that was signature-verified only, plus
two pre-existing shipped-app defects:

- `plan_prune_irs` read report keys that never existed (`prunable`/`prune`;
  the engine's dry-run report calls them `orphans`), so the confirm modal for
  a destructive prune always claimed there was nothing to prune **while
  confirming went on to delete for real**. Shipped in v0.1.0–0.3.0.
- `DeviceService`'s 5 s join versus a 51 s verb (#26, above) — also shipped.
- `push_ir` treated the engine's soft failures (`upload_failed`,
  `not_yet_registered`, `hash_mismatch`) as success, because it checked
  `outcome != "upload_error"` instead of the per-hash `ok`.
- `delete_ir` discarded the engine report, reporting a device that refused the
  removal — and the wedged registry-gone/file-left state — as a clean delete.
- Device-unreachable classification was duplicated across `_session`, `_op`
  and `plan_prune_irs`; consolidated into one rule so a healthy device's abort
  no longer flips the whole app offline.
- The engine floor moved to `helixgen>=0.31`: below it a pushed IR never
  reappears in `list-irs` (helixgen-core's `-11` listing-cache heal), which
  would read as a TUI regression.

## Process note

The suite's original plan delegated design decisions to the implementer, so
every review round relitigated them: 12 fix rounds across 5 launches, ~8 hours,
`REVIEW_DONE` never emitted, fix-commit diffstats oscillating
(`410 → 142 → 330 → 180 → 258 → 373 → 90 → 240 → 122 → 129 → 11`) with round
12 rewriting round 6's design of the same rule. The close-out design states
those decisions as settled fact. The general lesson — a pre-launch plan lint
and a review-loop circuit breaker — is filed as workspace backlog #100.

## Deferrals

- **#25** live-suite brittleness (unfixed review findings)
- **#26** the fix for the confirmed timeout defect — its own brainstorm
- **#27** live-suite safety helpers have no offline test

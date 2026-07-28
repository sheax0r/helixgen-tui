# Live smoke suite (#5) — close-out design

Status: approved 2026-07-28. Supersedes the open decisions in
`docs/plans/completed/2026-07-27-live-smoke-suite.md`.

## Why this document exists

The live smoke suite for `RealDevicePort` (backlog #5) was built on the
`live-smoke-suite` branch and works — it found and fixed real defects. But its
plan **delegated design decisions to the implementer** ("register a `live`
marker **or** make the gate a hard skip — whichever keeps a plain `pytest`
invocation from firing device writes by accident. State the choice"). Every
review round relitigated those choices, so each round's redesign became fresh
code for the next round to review: **12 fix rounds across 5 launches, ~8 hours,
`REVIEW_DONE` never emitted.** The fix-commit changed-line counts oscillated
rather than shrank — `410 → 142 → 330 → 180 → 258 → 373 → 90 → 240 → 122 →
129 → 11` — with round 12 rewriting round 6's design of the same
device-unreachable classification rule.

This document therefore states the decisions as **settled fact**, so the
close-out plan implements rather than chooses. The general lesson is filed as
workspace backlog #100 (pre-launch plan lint + review-loop circuit breaker).

## Decisions (settled — do not re-open)

These are what the branch converged on. They are correct; they were simply
never written down as decisions.

1. **Gating is a hard skip at collection**, unless `HELIXGEN_TUI_LIVE=1`.
   `tests/live` stays **inside** the default `testpaths` on purpose:
   collecting-then-skipping keeps the gate visible in `-ra` output instead of
   silently absent. A `live` marker is registered in `pyproject.toml` so `-m
   live` selection works.
2. **Device-backed tests additionally require a TCP-connect probe** of the
   Stadium's ZMQ ROUTER port (2002) — the device ignores ICMP, so ping is
   useless. Tests of the offline-first hinge need only the env gate.
3. **Engine floor is `helixgen>=0.31`, and violating it is a failure, not a
   skip.** Below that a pushed IR never reappears in `list-irs`
   (helixgen-core #38 / the `-11` listing-cache heal), so the IR tests would
   fail as though the TUI had regressed. A missing block library, missing
   device IP, or unreachable device is a **skip**; a too-old engine is a
   **failure**.
4. **`restore` and `sync_all(gc=True)` are excluded from live writes.**
   `restore` overwrites an existing preset (core's live suite excludes it for
   the same reason); the GC phase would delete real unreferenced pool presets
   against the scratch manifest, invisible to the state guard. Only their
   plan/unsupported paths are asserted.
5. **All local helixgen state is redirected to a session scratch dir**
   (`HELIXGEN_HOME`, `HELIXGEN_SETLISTS`, `HELIXGEN_DEVICE_SLOTS`,
   `HELIXGEN_IRS`, `HELIXGEN_IRHASH_CACHE`, `HELIXGEN_DEVICE_BACKUPS`,
   `HELIXGEN_PREFS`), by plain `os.environ` mutation restored at teardown so
   the in-process port and every CLI subprocess see the same scratch state.
   `HELIXGEN_LIBRARY` alone points at the user's real block library,
   read-only; absent library means skip.
6. **Every device artifact is `HGTEST`-prefixed and torn down in a
   finalizer**, including on failure; teardown never asserts.
7. **The device-state guard has a known confound**: another process committing
   to `~/.helixgen` mid-run trips it. That is not a suite leak, and the
   guard's docstring must say how to tell the two apart. (Observed
   2026-07-27: a concurrent `device normalize` session committed at
   18:47–18:52.)

## Scope

**In:** one end-to-end hardware run of the suite in its current form; triage
of whatever that run surfaces; empirical confirmation of backlog #26; the
close-out paperwork.

**Out:** any fix for #26 (see below); new suite coverage; the deferrals in
backlog #25 and #27.

## Task 1 — hardware re-run and triage

The suite's only hardware run happened before twelve rounds of edits, several
touching the port's classification logic. It has never been run end-to-end in
its current form.

**The triage rule** (stated so no round has to invent one):

| Failure cause | Action |
|---|---|
| `RealDevicePort` defect | Fix on this branch, failing test first |
| Engine defect | File in **helixgen-core**'s backlog; `xfail` here referencing the entry number. Never patch engine behavior in this repo |
| Environment shortfall (no library, no IR, device busy) | `skip` with a stated reason |

**Acceptance:** the run completes; every non-pass is explained by exactly one
row above; the device is left clean (0 `HGTEST` artifacts, no held leases).

## Task 2 — confirm backlog #26 at the service layer

Backlog #26 claims `DeviceService`'s 5 s join is shorter than the verbs it
guards, so Prune and Sync report a false timeout **while the daemon thread
keeps mutating the device**. That is currently an inference, not a
measurement.

Note the live suite **structurally cannot** see this: every test drives
`real_port` directly, never through `DeviceService`. So confirmation needs one
test at the service layer, not another live-port test.

**Work:** one test driving a verb end to end through `DeviceService`; record
measured wall-clock for `plan_prune_irs` and a sync against the 5 s join.

**Acceptance:** backlog #26 carries real numbers and says **confirmed** or
**refuted**.

**Explicitly out of scope: the fix.** The entry's own fix is a UX decision
(per-op timeouts versus an in-flight indicator), and deciding it inside a
close-out is the exact mistake this document exists to prevent. It gets its
own brainstorm and plan.

## Task 3 — close-out

Findings doc; backlog #5 closed with its deferrals listed (#25/#26/#27); the
`CLAUDE.md` and README live-suite sections already on the branch verified
accurate against final behavior; version and plan retirement checked.

## Abort contract

Stated in the plan itself, and binding:

- **Stop after 3 fix rounds** without `REVIEW_DONE`.
- **Stop the moment a round's diffstat exceeds the round before it.**
- On trip: **park the branch and report. Do not re-run.** Another
  `ralphex -r` buys commit N+1, not convergence.

Launch from a real terminal, not a harness background task — four background
launches were reaped mid-review on 2026-07-27, each losing 45–90 minutes of
review work. One ralphex at a time: concurrent runs share the account session
limit.

## Verification

- `uv run pytest -q` — offline suite; must stay green and must skip everything
  under `tests/live/`.
- `uv run ruff check .` — lint (CI pins `ruff==0.15.0`; repo-wide
  `ruff format` drift is pre-existing and out of scope).
- `HELIXGEN_TUI_LIVE=1 uv run pytest tests/live -q` — the hardware run
  Task 1 exists to perform.

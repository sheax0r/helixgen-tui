# Plan: live smoke suite (#5) — close-out

## Context

Closes out `docs/BACKLOG.md #5` on the `live-smoke-suite` branch. Design:
`docs/superpowers/specs/2026-07-28-live-smoke-suite-closeout-design.md` —
**read it first**; it states as settled fact every decision the previous
plan left open (gating, exclusions, engine floor, safety model). Do not
re-open them. The previous plan's delegation of those choices is why its
review ran 12 fix rounds across 5 launches without ever emitting
`REVIEW_DONE`.

This is a **close-out**: verify, triage, land. No new suite coverage, no
new features.

### Abort contract — binding

- Stop after **3 fix rounds** without `REVIEW_DONE`.
- Stop the moment a round's diffstat **exceeds the round before it**.
- On trip: park the branch and report. **Do not re-run.**

### Environment

- Stadium XL, fw 1.3.2 b1340, reachable; `helixgen` 0.32.0 installed
  (floor for this suite is `>=0.31`).
- Run tests with the repo venv: `uv run pytest -q` / `uv run ruff check .`.
- One ralphex at a time; check no other helixgen process holds a device
  lease before the hardware run (`helixgen device lock --status`).

### Task 1: Hardware re-run and triage

- [ ] Confirm no other process holds a device lease, then run the suite
      end to end: `HELIXGEN_TUI_LIVE=1 uv run pytest tests/live -q`.
      Record the verbatim result (this is its first run since twelve rounds
      of edits, several touching the port's classification logic)
- [ ] Resolve every non-pass by the triage rule, which is fixed — do not
      invent a different one:
      **(a)** `RealDevicePort` defect → fix on this branch, failing test
      first;
      **(b)** engine defect → file a numbered entry in **helixgen-core**'s
      `docs/BACKLOG.md`, `xfail` the test here referencing that number,
      never patch engine behavior in this repo;
      **(c)** environment shortfall (no block library, no registered IR,
      device busy) → `skip` with a stated reason
- [ ] Re-run until every non-pass falls under exactly one rule above
- [ ] Verify the device is left clean: 0 `HGTEST` presets/setlists/IRs, no
      held leases, player's active preset restored

### Task 2: Confirm backlog #26 at the service layer

- [ ] Add ONE test driving a verb end to end through `DeviceService`
      (`src/helixgen_tui/core/device.py`). The live suite structurally
      cannot see this defect — every live test drives `real_port` directly,
      never through the service — so this test belongs with the offline
      service tests, not in `tests/live/`
- [ ] Measure and record actual wall-clock for `plan_prune_irs` and a sync
      against the service's 5 s join (`timeout: float = 5.0`,
      `DeviceService.__init__`; `app.py`'s `on_mount` never overrides it)
- [ ] Update `docs/BACKLOG.md #26` with the measured numbers and a verdict:
      **confirmed** or **refuted**. If confirmed, state that the daemon
      thread keeps running and keeps mutating the device after the timeout
      is reported — a false failure over a write that lands
- [ ] **Do NOT fix it.** The fix is a UX decision (per-op timeouts versus an
      in-flight indicator) and gets its own brainstorm and plan. Deciding it
      here is the exact failure mode this plan exists to avoid

### Task 3: Close-out

- [ ] Write `docs/superpowers/specs/2026-07-28-live-smoke-suite-findings.md`:
      the hardware run's verbatim results, what triage did with each
      non-pass, the #26 measurement, and anything deferred
- [ ] Close `docs/BACKLOG.md #5` with a one-line note pointing at the
      findings doc, listing the live deferrals (#25/#26/#27) — or, if the
      suite could not be fully validated, rewrite the entry to say precisely
      what remains and why
- [ ] Verify the `CLAUDE.md` and README live-suite sections already on this
      branch describe final behavior (gating, env vars, safety posture,
      exclusions) — correct them if the hardware run changed anything
- [ ] Confirm the version bump and plan retirement are consistent:
      `pyproject.toml`, `src/helixgen_tui/__init__.py` and `uv.lock` agree,
      and this plan moves to `docs/plans/completed/`

## Validation Commands

Run from the repo root:

- `uv run pytest -q` — offline suite; must stay green and must skip
  everything under `tests/live/`
- `uv run ruff check .` — lint. CI pins `ruff==0.15.0`; repo-wide
  `ruff format` drift is pre-existing (backlog #24) and out of scope

Hardware (REQUIRED — Task 1 exists to perform it; a green offline suite
alone does NOT satisfy it):

- `HELIXGEN_TUI_LIVE=1 uv run pytest tests/live -q`

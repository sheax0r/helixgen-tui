# Plan: <title>

<!--
ralphex plan scaffold. Copy to docs/plans/<yyyy-mm-dd>-<slug>.md, fill in,
then run `ralphex --worktree docs/plans/<name>.md` against it. Keep tasks
small and checkbox-granular — ralphex works the unchecked boxes top to
bottom and checks them off as it goes. Move the finished plan to
docs/plans/completed/ when done (ralphex does this automatically on success).
-->

## Context

One short paragraph: what this change is, why now, and any backlog entry it
implements (e.g. `docs/BACKLOG.md #NN`). Link relevant specs under
`docs/superpowers/specs/` if they exist. Remember the repo rules: TDD
(failing test first, Textual pilot for screen logic), TUI stays
view/controller over the `helixgen` package (no `.hsp` parsing, no protocol
logic, no engine changes here — those land in helixgen-core first),
device writes are explicit user actions never navigation side effects.

### Task 1: <name>

- [ ] Write the failing test(s) first (see the matching `tests/` screen/service test for the established pilot + fake-service pattern)
- [ ] Run it to confirm it fails for the expected reason
- [ ] Implement the minimal change to make it pass
- [ ] Run the tests and confirm they pass
- [ ] Update any user-facing surface the change touches: `README.md` key/tab tables, help overlay, key-hints footer

### Task 2: <name>

- [ ] ...

<!-- Add more `### Task N:` sections as needed. Defer anything punted to
docs/BACKLOG.md as a numbered entry, not a TODO comment. -->

## Validation Commands

Run from the repo root:

- `uv run pytest` — full offline test suite (Textual pilot screen tests use
  fake services; no device required).
- `uv run ruff check .` — lint.

Opt-in (NOT part of default validation — requires a real Helix Stadium on
the LAN and mutates device state; preapproved for test runs driven from the
helix workspace, but keep to expendable slots/setlists and never leave the
device in a broken state):

- Any test marked/guarded as live-device — run only the impact area matching
  the change.

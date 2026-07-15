# helixgen-tui

Terminal UI for helixgen: manage the tone library, setlists, and a Line 6
Helix Stadium over the LAN from the terminal. **Design phase — no code yet.**
The design spec must be brainstormed and written (backlog #1) before any
implementation.

**Repo family (all under `sheax0r`):**
[`helixgen-core`](https://github.com/sheax0r/helixgen-core) is the Python
package `helixgen` — libs, CLI, MCP server, and the authoritative docs
(`docs/CLI.md`, `docs/recipe-reference.md`, `docs/stadium-app-parity.md`,
protocol references); [`helixgen`](https://github.com/sheax0r/helixgen) is
the Claude Code plugin/skills repo. This repo consumes core as a PyPI
dependency (package name `helixgen`, `[device]` extra for network control) —
**never vendor or copy core source here**; if the TUI needs an engine change,
it lands in helixgen-core first.

**The project backlog lives at `docs/BACKLOG.md`** — check it before starting
new work; deferred work and punted review findings get a numbered entry
there, not a TODO comment.

## Product ground rules

- **Slots are invisible.** The UI speaks in tones and setlists only — slot
  addresses (`1A`..`8D`) are an implementation detail the user never sees or
  types. This is the tone-library model's "slots are just addresses" taken to
  its conclusion, and it is non-negotiable (core backlog #29).
- **Librarian-first.** V1 is the management surface: tones, setlists, sync,
  IRs, plus setting the **active tone** on the device. The shell is designed
  from day one for multiple switchable screens (signal-flow editor, global
  settings, tuner/meters come later).
- **Long-term goal:** full parity with the Helix Stadium desktop app, per
  helixgen-core's `docs/stadium-app-parity.md` coverage matrix.
- **Engines live in core.** The TUI is a view/controller over helixgen's
  library + device APIs (`helixgen.device`, the setlist manifest, sync). No
  protocol logic, no `.hsp` parsing, no hashing in this repo.
- **Device writes are real.** The same write-gating mentality as core's
  CLI applies: reads are free; anything that mutates the device (sync,
  install, delete, live ops) must be an explicit, visible user action in the
  UI — never a side effect of navigation. The Stadium's network stack is
  flaky: surface retry affordances, don't hang the UI on a dropped frame.

## Open decisions (settle in the design spec, not in code)

- TUI stack: Textual vs urwid vs pure-stdlib curses. Core's "pure stdlib"
  rule does not bind this repo, but the dependency choice is deliberate and
  spec'd, not defaulted.
- Offline behavior: what works with no device reachable, and how sync state
  is presented.
- Packaging: `helixgen-tui` PyPI name is available (verified 2026-07-14).

## Development workflow

- **Worktrees, branched from fresh `github/main`.** All non-trivial work
  happens in a git worktree whose branch starts from freshly-fetched
  `github/main` (the GitHub remote is named **`github`**, not `origin`) —
  never commit directly on local `main`.
- **Adversarial review before shipping.** Before merging a PR, dispatch at
  least one independent review subagent prompted to *break* the change (find
  bugs, regressions, spec violations — not summarize it). Confirmed findings
  are fixed or explicitly deferred to `docs/BACKLOG.md`. Major changes also
  get a committed review doc in `docs/superpowers/specs/`.
- **Design docs + plans** live in `docs/superpowers/specs/` and
  `docs/superpowers/plans/`, same shape as helixgen-core.
- **Backlog discipline.** `docs/BACKLOG.md` is this repo's single backlog.
- TDD throughout: failing test first, then minimal implementation.
- **Never commit paid IR packs or personal device exports** (user rule from
  core; applies here if fixtures ever creep in).

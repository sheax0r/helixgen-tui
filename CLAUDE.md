# helixgen-tui

Terminal UI for helixgen: manage tone library, setlists, Line 6 Helix Stadium over LAN from terminal. **Design phase — no code yet.** Design spec must be brainstormed + written (backlog #1) before any implementation.

**Repo family (all under `sheax0r`):**
[`helixgen-core`](https://github.com/sheax0r/helixgen-core) is Python package `helixgen` — libs, CLI, MCP server, authoritative docs (`docs/CLI.md`, `docs/recipe-reference.md`, `docs/stadium-app-parity.md`, protocol references); [`helixgen`](https://github.com/sheax0r/helixgen) is Claude Code plugin/skills repo. This repo consumes core as PyPI dependency (package name `helixgen`, `[device]` extra for network control) — **never vendor or copy core source here**; TUI need engine change, it lands in helixgen-core first.

**Project backlog lives at `docs/BACKLOG.md`** — check before starting new work; deferred work + punted review findings get numbered entry there, not TODO comment.

## Product ground rules

- **Slots are invisible.** UI speaks tones + setlists only — slot addresses (`1A`..`8D`) are implementation detail user never sees or types. Tone-library model's "slots are just addresses" taken to conclusion. Non-negotiable (core backlog #29).
- **Librarian-first.** V1 = management surface: tones, setlists, sync, IRs, plus setting **active tone** on device. Shell designed day one for multiple switchable screens (signal-flow editor, global settings, tuner/meters later).
- **Long-term goal:** full parity with Helix Stadium desktop app, per helixgen-core's `docs/stadium-app-parity.md` coverage matrix.
- **Engines live in core.** TUI = view/controller over helixgen's library + device APIs (`helixgen.device`, setlist manifest, sync). No protocol logic, no `.hsp` parsing, no hashing in this repo.
- **Device writes are real.** Same write-gating mentality as core's CLI: reads free; anything mutating device (sync, install, delete, live ops) must be explicit, visible user action in UI — never side effect of navigation. Stadium network stack flaky: surface retry affordances, don't hang UI on dropped frame.

## Open decisions (settle in the design spec, not in code)

- TUI stack: Textual vs urwid vs pure-stdlib curses. Core's "pure stdlib" rule not binding here, but dependency choice deliberate + spec'd, not defaulted.
- Offline behavior: what works with no device reachable, how sync state presented.
- Packaging: `helixgen-tui` PyPI name available (verified 2026-07-14).

## Development workflow

- **Worktrees, branched from fresh `github/main`.** All non-trivial work in git worktree whose branch starts from freshly-fetched `github/main` (GitHub remote named **`github`**, not `origin`) — never commit directly on local `main`.
- **Adversarial review before shipping.** Before merging PR, dispatch at least one independent review subagent prompted to *break* change (find bugs, regressions, spec violations — not summarize). Confirmed findings fixed or explicitly deferred to `docs/BACKLOG.md`. Major changes also get committed review doc in `docs/superpowers/specs/`.
- **Design docs + plans** live in `docs/superpowers/specs/` and `docs/superpowers/plans/`, same shape as helixgen-core.
- **Backlog discipline.** `docs/BACKLOG.md` = this repo's single backlog.
- TDD throughout: failing test first, then minimal implementation.
- **Never commit paid IR packs or personal device exports** (user rule from core; applies here if fixtures ever creep in).

## ralphex

Implementation tasks driven from the helix coordination workspace run via [ralphex](https://github.com/umputun/ralphex) plan files in `docs/plans/` (scaffold: `docs/plans/TEMPLATE.md`); completed plans move to `docs/plans/completed/`. The launcher syncs local `main` from `github/main` before each run. Review = ralphex's built-in pipeline (`external_review_tool = none` in `.ralphex/config`) — the adversarial-review step above still applies before merge. `default_branch = main` is pinned in `.ralphex/config` because the remote is named `github` (not `origin`), so ralphex can't auto-detect the default branch from `origin/HEAD`. `.ralphex/config` is tracked; the `.ralphex/worktrees/` and `.ralphex/progress/` runtime dirs are gitignored.

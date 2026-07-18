# helixgen-tui backlog

Numbering is local to this repo. The originating entry is helixgen-core's
backlog #29 (helixgen-tui), which carries the product mandate: cover
everything the Stadium desktop app does, slots invisible, own design spec
before any code.

- ✅ **#1 Design spec** — shipped 2026-07-17:
  `docs/superpowers/specs/2026-07-17-tui-v1-librarian-design.md`. All open
  questions settled with the user (Textual; tabbed screens; offline-first;
  tiered mutation confirmation; direct Python API behind the
  `helixgen_tui.core` adapter; layered fake-core + Pilot testing).
  Implementation plan is the next step.
- ✅ **#2 Packaging + CI skeleton** — shipped 2026-07-17 (PR #1): pyproject
  (`helixgen-tui`, `helixgen[device]>=0.26`), console script + `-m` entry,
  pytest + ruff CI, publish workflow.
- **#3 Ask core to bless a minimal stable Python API surface** for the TUI's
  needs (library/manifest/device reads, mutation verbs, locks) — the TUI
  binds the Python API directly (design D5); today only the CLI is core's
  documented contract. File the core-side entry when implementation starts
  and the real import list is known.
- **#4 Tone-designer chat screen (first post-v1 screen)** — user-requested
  2026-07-17: if Claude Code is installed locally, a fifth tab hosts a
  conversation where the user describes a tone and Claude authors it into
  the library via the helixgen plugin skills. Requirements (auth reuse,
  D4-modal permission bridging, graceful degradation, library refresh) are
  settled in the v1 design spec's "first post-v1 screen" section; binding
  choice (Agent SDK vs headless CLI) deferred to build time.

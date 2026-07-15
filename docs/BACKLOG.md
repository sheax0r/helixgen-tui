# helixgen-tui backlog

Numbering is local to this repo. The originating entry is helixgen-core's
backlog #29 (helixgen-tui), which carries the product mandate: cover
everything the Stadium desktop app does, slots invisible, own design spec
before any code.

- **#1 Design spec (brainstorm → `docs/superpowers/specs/`)** — the
  brainstorm started 2026-07-14 and settled two things before being paused
  for the repo split: **v1 is the librarian** (tones, setlists, sync, IRs)
  **plus setting the active tone**, and the shell must support **switchable
  screens** for future interfaces (editor, global settings, tuner/meters).
  Still open: TUI stack (Textual vs urwid vs curses — the stack question was
  posed but not answered), screen inventory + navigation model, offline
  behavior, how device-mutating actions are confirmed, testing strategy.
  Output: a committed design spec, then an implementation plan.
- **#2 Packaging + CI skeleton** — pyproject (`helixgen-tui`, PyPI name
  verified available 2026-07-14), depends on `helixgen[device]` from PyPI
  (blocked on core backlog #55 — first PyPI publish), pytest + lint CI.

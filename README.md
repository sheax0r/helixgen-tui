# helixgen-tui

A terminal UI for [helixgen](https://github.com/sheax0r/helixgen-core):
manage your tone library, setlists, and a Line 6 Helix Stadium over the LAN
— from the terminal, no editor app.

> **Status: design phase.** No code yet — the design spec (librarian-first,
> multi-screen shell) is being written. See `docs/BACKLOG.md`.

## Repo family

| Repo | What it is |
|---|---|
| [helixgen-core](https://github.com/sheax0r/helixgen-core) | The `helixgen` Python package: libs, CLI, MCP server |
| [helixgen](https://github.com/sheax0r/helixgen) | The Claude Code plugin — `/tone`, `/setup`, `/device` skills + marketplace |
| **helixgen-tui** (this repo) | Terminal UI for tones, setlists, and device control |

## What it will do

First usable version: the **librarian** — browse and manage tones, setlists,
and device sync, plus setting the **active tone** on the hardware — inside a
shell designed from day one to host more screens (signal-flow editor, global
settings, tuner/meters) as they're built. The long-term goal is full parity
with the Helix Stadium desktop app (tracked in helixgen-core's
`docs/stadium-app-parity.md`).

**Design principle: slots are invisible.** The UI speaks in tones and
setlists only — slot addresses like `5A` are an implementation detail the
user never sees or types.

> ⚠️ **Unofficial tool — use at your own risk.** Not affiliated with or
> endorsed by Line 6 / Yamaha. Line 6, Helix, and HX are trademarks of
> Yamaha Guitar Group, Inc. The MIT [LICENSE](LICENSE) disclaims all
> warranty.

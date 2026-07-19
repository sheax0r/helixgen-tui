# helixgen-tui

A terminal UI for [helixgen](https://github.com/sheax0r/helixgen-core):
manage your tone library, setlists, and a Line 6 Helix Stadium over the LAN
— from the terminal, no editor app.

> ⚠️ **Unofficial tool — use at your own risk.** Not affiliated with or
> endorsed by Line 6 / Yamaha. Line 6, Helix, and HX are trademarks of
> Yamaha Guitar Group, Inc. The MIT [LICENSE](LICENSE) disclaims all
> warranty.

## Repo family

| Repo | What it is |
|---|---|
| [helixgen-core](https://github.com/sheax0r/helixgen-core) | The `helixgen` Python package: libs, CLI, MCP server |
| [helixgen](https://github.com/sheax0r/helixgen) | The Claude Code plugin — `/tone`, `/setup`, `/device` skills + marketplace |
| **helixgen-tui** (this repo) | Terminal UI for tones, setlists, and device control |

## Install

```sh
uv tool install helixgen-tui
# or
pipx install helixgen-tui
```

Then run it as `helixgen-tui` or the shorter `hxg`.

## Usage

The app is the **librarian**: browse and manage tones, setlists, and device
sync, plus setting the **active tone** on the hardware — all inside a
tabbed shell:

| Tab | Key | What it does |
|---|---|---|
| Library | `1` | Browse tones, view details, filter (`/`), make a tone active, sync it to the device |
| Setlists | `2` | Manage setlist membership and order, filter (`/`), sync a setlist or all setlists |
| IRs | `3` | Push local IRs to the device, filter (`/`), rename/delete/prune device IRs |
| Device | `4` | Device info, active tone, backup/restore, lock status, retry connect |

Press `?` anywhere for the full key-binding reference, `q` to quit.

**Fuzzy filter:** `/` opens a filter on the Library, Setlists, and IRs screens
(on IRs it applies to whichever pane has focus — moving focus re-targets it, so
the newly focused pane gets ranked and the other returns to its native order).
Type part of a name — matching is an ordered subsequence, so `jcm` finds
"JCM800 Crunch"; matches sort best-first and the matched characters are
highlighted, and the cursor rides the top hit as you type. `enter` in a filter
acts on the highlighted row — the best match — and never mutates anything
(activate, sync, push, delete stay on their own keys). `escape` clears the
filter, and on IRs it unwinds one step at a time, innermost first — an open
rename prompt goes before a live query, so a filter typed before renaming takes
a second `escape`. The add-tone picker in Setlists filters the same way, where
`enter` adds the highlighted match.

**Tone editor:** press `enter` on a Library tone to open its signal chain. The
chain renders left-to-right — an input node, the blocks (both DSP paths stacked
when parallel-routed), then the output node. Arrow keys walk the chain; `tab`
switches to the params inspector, where `left`/`right` nudge a value and `enter`
types one. Structural keys: `a` add a block, `x` remove, `b` bypass/enable, `w`
swap the model. Selecting the output node edits its level/pan; the input node's
source is read-only. Add/remove refuse on a parallel-routed path. Edits write to
the local library file on `s` — never to the device.

**Offline-first:** the app works fully with no device on the LAN — Library,
Setlists, and IRs stay browsable from local state. Device-mutating actions
(activate, sync, push, backup, restore, ...) simply refuse with a reason in
the status bar when no Helix is reachable, and reconnect automatically (or
via `r` on the Device tab) once one is.

**Design principle: slots are invisible.** The UI speaks in tones and
setlists only — slot addresses like `5A` are an implementation detail the
user never sees or types.

> **Note:** device *restore* and device-side *tone delete* are not yet wired —
> they await core-side verbs (a restore that carries its target preset, and a
> single-pool-preset delete). The UI surfaces a clear reason until then. See
> `docs/BACKLOG.md` #6.

The long-term goal is full parity with the Helix Stadium desktop app
(tracked in helixgen-core's `docs/stadium-app-parity.md`); this v1 ships the
librarian and the tone editor (param editing plus signal-flow editing —
block add/remove/swap, bypass, output level/pan), with more screens (global
settings, tuner/meters) to follow. See `docs/BACKLOG.md`.

## Development

Managed with [uv](https://docs.astral.sh/uv/); the package layout is
`src/helixgen_tui/`, depending on `helixgen[device]` from PyPI (never vendor
core source here).

```sh
uv run pytest          # test suite
uv run ruff check .    # lint
uv run helixgen-tui    # run the app
uv build               # sdist + wheel
```

CI (GitHub Actions) runs ruff + pytest on every PR and push to `main`;
`publish.yml` releases to PyPI via OIDC trusted publishing on `v*` tags.

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
parks on the highlighted row — the best match — and hands focus back to the
list, so `s`/`p`/`d` act on it instead of typing into the filter; it never
mutates anything itself (activate, sync, push, delete stay on their own keys).
The query stays live after `enter`, so you keep arrowing the narrowed list.
`escape` clears the
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

**Setlist sync:** `✓` marks a setlist the device mirrors; `○` is a local
draft. `S` syncs the selected setlist and opts it into mirroring; `A` syncs
every `✓` setlist and never opts a draft in — so a library where nothing has
been synced yet shows *(no synced setlists to sync)* in the confirm. Both also
remove device presets for tones you have **unsynced** since the last run,
which is why the sync-all confirm says so; a preset a live setlist still
references is left alone and named in the status bar.

**Offline-first:** the app works fully with no device on the LAN — Library,
Setlists, and IRs stay browsable from local state. Device-mutating actions
(activate, sync, push, backup, restore, ...) simply refuse with a reason in
the status bar when no Helix is reachable, and reconnect automatically (or
via `r` on the Device tab) once one is. A device that *is* reachable but
refuses or aborts an operation is a third state: the header stays connected
and the panel or status bar shows the engine's own reason and remediation
text, rather than the app going offline over one dropped frame.

**Design principle: slots are invisible.** The UI speaks in tones and
setlists only — slot addresses like `5A` are an implementation detail the
user never sees or types.

> **Note:** device *restore* and device-side *tone delete* are not yet wired —
> they await core-side verbs (a restore that carries its target preset, and a
> single-pool-preset delete). The UI surfaces a clear reason until then. See
> `docs/BACKLOG.md` #6.
>
> Two device-IR verbs can report something short of a clean success, both by
> design: deleting an IR (`d`) can half-succeed — the Helix removes the registry
> entry but leaves the backing file behind, reported as *"registry entry
> removed; backing file left on the device"*; clean that up with `helixgen
> device delete-ir <hash> --force-wedge --yes` (the TUI does not offer the
> forced delete). And prune (`P`) refuses in the status bar, without opening a
> confirm, whenever the engine can't verify some local tones' IR references —
> a confirm it could only fail is worse than no confirm. One library tone with a
> missing `.hsp` is enough to refuse every prune from then on, and the TUI offers
> no way to fix it from inside the app; tracked in `docs/BACKLOG.md` #28.
>
> Also known: long device operations — *sync all* and *prune* especially — can
> report `timed out` in the status bar after ~5s while the operation is still
> running on the device and goes on to complete. The failure is in the
> reporting, not the write; nothing is rolled back. Re-check the tab (`r` on
> Device) before retrying rather than firing the same write again. Tracked in
> `docs/BACKLOG.md` #26.

The long-term goal is full parity with the Helix Stadium desktop app
(tracked in helixgen-core's `docs/stadium-app-parity.md`); this v1 ships the
librarian and the tone editor (param editing plus signal-flow editing —
block add/remove/swap, bypass, output level/pan), with more screens (global
settings, tuner/meters) to follow. See `docs/BACKLOG.md`.

## Development

Managed with [uv](https://docs.astral.sh/uv/); the package layout is
`src/helixgen_tui/`, depending on `helixgen[device]>=0.31` from PyPI (never
vendor core source here). The `0.31` floor is a runtime one, not just a test
one: below it a pushed IR never re-appears in the device IR listing (core #38),
so the IRs tab misreports what is on the device.

```sh
uv run pytest          # test suite
uv run ruff check .    # lint
uv run helixgen-tui    # run the app
uv build               # sdist + wheel
```

The suite is offline by default: `tests/live/` (the real device port against
real hardware, real device writes) hard-skips at collection unless
`HELIXGEN_TUI_LIVE=1` — the ~20 skips in a normal run are that gate. To run it
against a Helix Stadium on the LAN:

```sh
HELIXGEN_TUI_LIVE=1 uv run pytest tests/live -q
```

It needs port 2002 TCP-reachable, an ingested block library, and a resolvable
device IP (`HELIXGEN_HELIX_IP`, else a `helixgen device discover` record) —
without any of those it skips rather than fails. An installed `helixgen` below
`0.31` is the one hard failure: below it a pushed IR never re-appears in
`list-irs` (core #38), so the IR tests would read as a TUI regression. All local
helixgen state is
redirected to a scratch dir for the run and every artifact is `HGTEST`-prefixed;
the safety model and the deliberately excluded verbs are documented in
`tests/live/conftest.py`.

Two recoveries worth knowing before you need them. A run killed outright
(SIGKILL, not Ctrl-C) leaves the machine's **real** advisory `all` device lease
held for up to its 1800s TTL, which blocks every other helixgen process on the
machine — clear it with `helixgen device unlock --force`. And a
`~/.helixgen changed during the test session` failure is not necessarily a
suite leak: another helixgen process (an editor, a parallel agent, a shell)
touching the real home fails the session the same way. Tell them apart by
re-running under an isolated home — `HELIXGEN_HOME=$(mktemp -d) uv run pytest`
— which still fails only if the suite really did leak.

CI (GitHub Actions) runs ruff + pytest on every PR and push to `main`;
`publish.yml` releases to PyPI via OIDC trusted publishing on `v*` tags.

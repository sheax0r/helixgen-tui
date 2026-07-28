# helixgen-tui

Terminal UI for helixgen: manage tone library, setlists, Line 6 Helix Stadium over LAN from terminal. **Past design phase — shipping.** V1 librarian plus the tone editor (param editing + signal-flow: block add/remove/swap, bypass, output level/pan) have shipped. Design specs live in `docs/superpowers/specs/`; work is tracked in `docs/BACKLOG.md`.

**Repo family (all under `sheax0r`):**
[`helixgen-core`](https://github.com/sheax0r/helixgen-core) is Python package `helixgen` — libs, CLI, MCP server, authoritative docs (`docs/CLI.md`, `docs/recipe-reference.md`, `docs/stadium-app-parity.md`, protocol references); [`helixgen`](https://github.com/sheax0r/helixgen) is Claude Code plugin/skills repo. This repo consumes core as PyPI dependency (package name `helixgen`, `[device]` extra for network control), pinned `helixgen[device]>=0.31` — **runtime floor, not test-only**: below it `push_ir` doesn't heal the device's `-11` IR listing cache (core #38), so IRs tab misreports what is on device. **Never vendor or copy core source here**; TUI need engine change, it lands in helixgen-core first.

**Project backlog lives at `docs/BACKLOG.md`** — check before starting new work; deferred work + punted review findings get numbered entry there, not TODO comment.

## Product ground rules

- **Slots are invisible.** UI speaks tones + setlists only — slot addresses (`1A`..`8D`) are implementation detail user never sees or types. Tone-library model's "slots are just addresses" taken to conclusion. Non-negotiable (core backlog #29).
- **Librarian-first.** V1 = management surface: tones, setlists, sync, IRs, plus setting **active tone** on device. Shell designed day one for multiple switchable screens (global settings, tuner/meters later; signal-flow editing shipped inside the tone editor).
- **Long-term goal:** full parity with Helix Stadium desktop app, per helixgen-core's `docs/stadium-app-parity.md` coverage matrix.
- **Engines live in core.** TUI = view/controller over helixgen's library + device APIs (`helixgen.device`, setlist manifest, sync). No protocol logic, no `.hsp` parsing, no hashing in this repo.
- **Device writes are real.** Same write-gating mentality as core's CLI: reads free; anything mutating device (sync, install, delete, live ops) must be explicit, visible user action in UI — never side effect of navigation. Stadium network stack flaky: surface retry affordances, don't hang UI on dropped frame.
- **Searching is never a write.** `enter` in a filter input acts on the highlighted row — which filtering has already parked on the best match — and stops there — activate/sync/push/delete/rename keep their own keys. Only a picker whose whole purpose is committing a choice (`AddToneModal`) acts on `enter`, and then only against local state. New filterable surfaces inherit this: `FilterableTableMixin.filter_on_enter` defaults to `move_cursor_to`, so overriding it is the deliberate act.
- **Real-port verbs fold the engine's report; they never hardcode `ok=True`.** helixgen's device layer signals per-item failure *inside* the returned dict (`ok`, `errors`, `warnings`, `note`, `file_removed`) and raises only for transport faults — four verbs in `core/real.py` shipped reporting success over engine refusals for exactly this reason (2026-07-27, spec `docs/superpowers/specs/2026-07-27-live-smoke-suite.md`). New verbs assert the report shape against the installed engine in an offline unit test. A `plan_*` feeding a destructive `ConfirmModal` **raises** on any condition the confirm couldn't survive — `DeviceService.query` reports it and the modal never opens; returning the reason as plan text offers a confirmable delete that can only fail.
- **Only a connect-class `HelixError` means the device is gone** (`_CONNECT_FAILURES` in `core/real.py`). Everything else the engine raises — a strict listing on a truncated reply, a dangling setlist reference, the prune confirm re-scan disagreeing — is an abort on a *reachable* device and must fail soft with the engine's remediation text, not flip the whole app offline. The connect messages are a closed set; the aborts are not, so classify on the former. They are string matches against the installed `HelixClient` (the engine has one exception class), so an offline test pins every marker to `inspect.getsource(HelixClient)` — a test raising its own copy of the string proves nothing. Classification happens **once**, in `_session` (plus the two verbs that connect themselves); reads propagate the abort to `DeviceService.query`'s error branch, which reports without flipping offline. Same split for `OSError`, but on **errno**, not class: the device layer does local disk work under the same guards (`backup_setlist` mkdir/write_bytes, `IrMapping.load`), so a blanket `except OSError` reported ENOSPC as "device offline" — and `EHOSTUNREACH`/`ENETUNREACH` are plain `OSError`, not `ConnectionError`, so a class check misses a device off the LAN. A test constructing `OSError("[Errno 65] ...")` leaves `errno` as `None` and proves nothing; pass the errno. The rule lives in ONE predicate (`_as_unreachable`) — three hand-copied `except` pairs were three places to drift. The one deliberate exception is the poll thread: `DeviceService._probe_once` catches everything and *does* report offline, because an escaping exception kills the daemon thread and freezes the header on its last state forever — it carries the reason into `DeviceStateVM.detail` so a persistent non-connect fault stays distinguishable from a device off the LAN. Screens tell the two apart by comparing against `core.device.DEVICE_OFFLINE`, never a repeated string literal.
- **Every listing the user acts on is `strict=True`.** `list_irs`/`list_presets` default to non-strict, which reads a timeout or a truncated reply as an empty/partial list. The IRs pane the user pushes to and deletes from, the name→cid resolution behind "'X' is not on the device", and `backup`'s preset set all turn that into a confident false claim — `backup_setlist`'s own listing is the non-strict default, so a dropped frame reported a green "backed up 0 preset(s)" over the user's only restore point (hence the port passing `presets=`). Strict raises instead and the abort fails soft with the engine's retry text. Pin it with a stub that records the kwarg, never a `getsource` grep for `list_irs(strict=True)`: that stays green when the keyword is dropped and the text left behind in a comment.
- **Engine report shapes get pinned to `inspect.getsource` of the engine function, never its docstring.** Every key the port folds (`ir_prune`'s `orphans`/`deleted`/`warnings`/`errors`, `delete_device_ir`'s `ok`/`file_removed`, `upload_missing_irs`'s `ok`/`note`) has an offline pin. A docstring pin is uncorrelated with the defect it claims to catch: it stays green while the engine documents keys it no longer emits, and goes red when the engine merely rewords prose. `inspect.getsource` *includes* the docstring, so strip it (`_engine_body` in the test module) — otherwise a bare `"<key>" in source` is a docstring pin wearing a source pin's name.
- **Test support code resolves engine-derived paths through the engine** — `helixgen_home()`, `locks_root()`, `discovery.resolve_ip()`, resolved at import before any fixture redirects `$HELIXGEN_HOME`. Never a hand-rolled copy of the env precedence: a drifted copy doesn't make a *guard* fail loudly, it makes it go inert (the real-home guard snapshotting an unrelated directory, so `before == after` holds trivially). Same reason the guard's `.git` exclusion matches against the path relative to the root.
- **List surfaces resolve selection through `FilterableTableMixin.selected()`** (`src/helixgen_tui/screens/filterable.py`) — never by parsing a row key back into a backing index. The mixin's `_visible` is the only valid cursor→item mapping; once rows are filtered or re-ranked, table position and backing position diverge. Row keys stay positional where display names duplicate (the IR panes) purely because `DataTable` rejects repeats — they carry no meaning, which is also why `rebuild_filtered` restores the cursor by *item*, not by key.

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
- **Live device suite (`tests/live/`) is opt-in.** Default `pytest` run and CI
  hard-skip it at collection — green, offline, no device writes possible. To run
  against real hardware: `HELIXGEN_TUI_LIVE=1 uv run pytest tests/live -q`
  (`-m live` selects the suite). Also needs: helixgen >=0.31, an ingested block
  library, the Stadium's ZMQ port 2002 TCP-reachable, and a resolvable device IP
  (`HELIXGEN_HELIX_IP`, else a `helixgen device discover` record — the scratch
  home has none). Missing library/IP/device = skip; engine below the pin = fail
  fast, rather than presenting core #38's IR-listing bug as a TUI regression.
  Safety posture:
  all local helixgen state redirected to scratch, upfront device backup,
  session-failing device state guard, `HGTEST`-prefixed artifacts only, session
  `all` advisory lease held for the run. Normative details + exclusions
  (`restore`, `sync_all(gc=True)`): `tests/live/conftest.py` docstring; findings:
  `docs/superpowers/specs/2026-07-27-live-smoke-suite.md`. Recovery, both
  non-obvious: a SIGKILL'd run leaves the machine's REAL `all` lease held for up
  to its 1800s TTL, blocking every other helixgen process — clear it with
  `helixgen device unlock --force`. A `~/.helixgen changed during the test
  session` failure can be another helixgen process rather than a suite leak;
  tell them apart by re-running under `HELIXGEN_HOME=$(mktemp -d) uv run pytest`.
- **Never commit paid IR packs or personal device exports** (user rule from core; applies here if fixtures ever creep in).

## ralphex

Implementation tasks driven from the helix coordination workspace run via [ralphex](https://github.com/umputun/ralphex) plan files in `docs/plans/` (scaffold: `docs/plans/TEMPLATE.md`); completed plans move to `docs/plans/completed/`. The launcher syncs local `main` from `github/main` before each run. Review = ralphex's built-in pipeline (`external_review_tool = none` in `.ralphex/config`) — the adversarial-review step above still applies before merge. `default_branch = main` is pinned in `.ralphex/config` because the remote is named `github` (not `origin`), so ralphex can't auto-detect the default branch from `origin/HEAD`. `.ralphex/config` is tracked; the `.ralphex/worktrees/` and `.ralphex/progress/` runtime dirs are gitignored.

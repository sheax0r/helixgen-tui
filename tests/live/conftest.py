"""Live smoke suite for ``RealDevicePort`` — the real port, the real engine,
a real Helix Stadium (backlog #5, spec D6).

Every other device test in this repo drives ``FakeDevicePort``;
``RealDevicePort`` (``src/helixgen_tui/core/real.py``) is signature-verified
only. This suite runs its verbs in-process against actual hardware and asserts
the shapes the TUI consumes (``DeviceStateVM``, ``IrVM``, ``MutationPlan``,
``OpResult``).

Opt-in gating
-------------
Everything under ``tests/live/`` is HARD-SKIPPED at collection time unless
``HELIXGEN_TUI_LIVE=1`` is set — the default ``pytest`` run (and CI) stays
green, offline, and incapable of firing device writes by accident, even on a
dev machine with a Helix on the LAN. ``tests/live`` stays inside the default
``testpaths`` on purpose: collecting-then-skipping keeps the gate visible in
``-ra`` output instead of silently absent. A ``live`` marker (registered in
``pyproject.toml``) is added to every test here so ``-m live`` selection works.

Device-backed tests additionally require a cheap TCP-connect probe of the
device's ZMQ ROUTER port (2002) to succeed — the Stadium ignores ICMP, so ping
is useless (the ``device`` fixture). Without the probe those tests skip; tests
of the offline-first hinge need only the env gate.

Run it::

    HELIXGEN_TUI_LIVE=1 uv run pytest tests/live -q

It also needs helixgen >=0.31 installed (below that a pushed IR never
re-appears in ``list-irs`` — helixgen-core #38 — and the IR tests would fail as
if the TUI had regressed, so ``_live_env`` fails fast instead), an ingested
block library, and a resolvable device IP. A missing library, IP, or device is
a SKIP; a too-old engine is a failure.

Safety model (encoded as fixtures)
----------------------------------
* ALL local helixgen state is redirected to a session scratch dir before any
  test runs (``_live_env``, autouse): ``HELIXGEN_HOME``,
  ``HELIXGEN_SETLISTS``, ``HELIXGEN_DEVICE_SLOTS``, ``HELIXGEN_IRS``,
  ``HELIXGEN_IRHASH_CACHE``, ``HELIXGEN_DEVICE_BACKUPS``,
  ``HELIXGEN_PREFS``. Only ``HELIXGEN_LIBRARY`` points at the user's real
  block library, read-only; the suite skips if it is absent. The redirect is
  plain ``os.environ`` mutation (restored at teardown) so both the in-process
  port under test and every CLI subprocess the safety net spawns see the same
  scratch state.
* The device IP is resolved BEFORE the home redirect (the engine's own
  ``discovery.resolve_ip()``: ``$HELIXGEN_HELIX_IP``, else the newest
  ``devices/*.json`` record) and pinned into ``HELIXGEN_HELIX_IP``, because
  the scratch home has no device records.
* An upfront ``device backup`` (to scratch) runs before the first device test
  (``device_backup``).
* Device state (user presets / setlists / IRs, via the engine CLI's
  ``--json`` verbs) is captured before the first device test and re-captured
  at session teardown; the session ITSELF FAILS if the normalized state
  changed (``device_state_guard``). Stale ``HGTEST`` leftovers from a crashed
  previous run are swept before the capture. ``device list --json`` defaults
  to ``--setlist user``, which IS the preset POOL (cid space -2, where every
  user preset lives), so pool leaks ARE covered by the diff. Two blind spots,
  stated honestly:
  (a) the ACTIVE edit buffer is not part of the diff (``make_active`` tests
  capture and restore the active preset themselves, but unsaved edit-buffer
  changes present before the run are discarded by design — saved presets are
  covered by the upfront backup);
  (b) setlist ENTRIES are not: ``device setlists --json`` lists the
  containers (``cid_``/``name``/``posi``), not the per-position references
  inside them, so a reference written into an untracked setlist without a
  matching pool change would not show up in the diff. Sync always writes the
  pool half too — which IS captured — so a leak is not invisible, just
  narrower than the container list suggests.
* The repo-wide session guard in ``tests/conftest.py`` verifies the user's
  real helixgen home (``$HELIXGEN_HOME``, else ``~/.helixgen``, resolved the
  same way and at the same time as ``_REAL_HELIXGEN`` below) is untouched at
  teardown, by full mtime snapshot. Two subtrees are excluded: the real lease
  root (``$HELIXGEN_LOCKS``, else ``<home>/locks`` — lease churn is this
  suite's whole point) and ``.git`` metadata (``~/.helixgen`` is a git repo,
  so an ambient ``git status`` refreshing the index is not a state leak).
* Every artifact the suite creates carries the ``HGTEST`` prefix; teardown
  helpers refuse to touch anything without it.

Device-lock strategy (the one this suite picked)
------------------------------------------------
The suite takes the REAL machine-local ``all`` advisory lease for the whole
run (label ``tui-live-suite``, via the engine CLI in the ``cli`` fixture) and
releases it at teardown, and passes a per-run ``HELIXGEN_LOCK_TOKEN`` so its
own in-process verbs and CLI calls pass through that lease. ``HELIXGEN_LOCKS``
deliberately stays REAL (not scratch): the point of the lease is excluding
OTHER helixgen processes on this machine from colliding with the run.

The engine CLI the safety net drives is the SAME interpreter/package the port
under test imports (``sys.executable -c "from helixgen.cli import cli; ..."``)
so there is no version skew between the state capture and the verbs.

Deliberately excluded verbs (and why)
-------------------------------------
* ``restore`` — it overwrites an existing preset's content in place; there is
  no ``HGTEST``-scoped way to exercise it (helixgen-core's live suite excludes
  it for the same reason). Only its unsupported/plan paths are asserted.
* ``sync_all(gc=True)`` — the GC phase (which only runs on the all-setlists
  sync) deletes device pool presets the manifest doesn't reference; against
  this suite's SCRATCH manifest that means EVERY real pool preset. The state
  guard would catch the damage after the fact, which is no use — the presets
  would already be gone. No TUI surface passes ``gc=True`` anyway
  (``screens/setlists.py`` passes ``False`` at every call site), so
  ``sync_all`` is covered with ``gc=False`` only (helixgen-core's live suite
  excludes ``sync --gc`` for the same reason).
  ``prune_irs`` — a real deletion too — stays in, but gated on the
  engine's own dry-run plan: it executes only when the sole orphan is the
  test's own ``HGTEST`` IR.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import uuid
from importlib.metadata import version
from pathlib import Path

import pytest
from helixgen.home import helixgen_home
from helixgen.locks import locks_root

#: Every artifact the suite creates carries this prefix; teardown helpers
#: refuse to touch anything without it.
HGTEST = "HGTEST"

DEVICE_PORT = 2002
LIVE_ENABLED = os.environ.get("HELIXGEN_TUI_LIVE") == "1"

_LIVE_DIR = Path(__file__).resolve().parent
#: The user's REAL helixgen home and lease root, resolved by the ENGINE's own
#: functions at import (i.e. BEFORE ``_live_env`` redirects ``$HELIXGEN_HOME``
#: to scratch). Re-deriving the precedence here is free to drift from the
#: engine, and the lock root is where that bites: the session ``all`` lease
#: exists to exclude every OTHER helixgen process on this machine, so writing it
#: to a root nobody reads makes the run's whole exclusion guarantee silently do
#: nothing.
_REAL_HELIXGEN = helixgen_home()
_REAL_LOCKS = locks_root()


def _resolve_device_ip() -> str | None:
    """The engine's own resolution chain ($HELIXGEN_HELIX_IP, else the newest
    persisted ``devices/*.json`` record), run at IMPORT — i.e. before
    ``_live_env`` redirects $HELIXGEN_HOME to scratch, which has no records.
    It opens no socket. A local copy of the chain would be free to drift from
    the engine's, which is the very skew this suite exists to detect.

    Anything unexpected is swallowed: this runs at COLLECTION time on every
    default (offline) run, so a raise here would break plain ``pytest`` for
    someone who never asked for the live suite."""
    try:
        # inside the try: an import error is exactly the "anything unexpected"
        # the docstring promises to swallow, and it was the one path left out.
        from helixgen.device.discovery import resolve_ip

        return resolve_ip(warn=False)  # warn=False: no stderr noise at collection
    except Exception:  # noqa: BLE001 — no configured device is a skip, not an error
        return None


DEVICE_IP = _resolve_device_ip()


def pytest_collection_modifyitems(config, items):
    """Mark everything under tests/live ``live``; hard-skip it all unless
    HELIXGEN_TUI_LIVE=1 (collection-time, so no fixture ever runs)."""
    skip = pytest.mark.skip(
        reason="live device suite is opt-in: set HELIXGEN_TUI_LIVE=1 "
        f"(device tests also need the Helix reachable on {DEVICE_IP}:{DEVICE_PORT})"
    )
    for item in items:
        # .resolve() both sides — _LIVE_DIR is resolved, and an unresolved
        # item path (symlinked checkout) would silently miss the gate.
        if _LIVE_DIR not in Path(str(item.fspath)).resolve().parents:
            continue
        item.add_marker(pytest.mark.live)
        if not LIVE_ENABLED:
            item.add_marker(skip)


# --------------------------------------------------------------------------
# scratch state + env redirect
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def real_library() -> Path:
    """The user's real block library — read-only. Skip the suite without it."""
    lib = Path(os.environ.get("HELIXGEN_LIBRARY", str(_REAL_HELIXGEN / "library")))
    if not (lib / "index.json").exists():
        pytest.skip(
            f"no block library at {lib} — the live suite needs a real "
            "ingested library (HELIXGEN_LIBRARY)"
        )
    return lib


@pytest.fixture(scope="session")
def scratch(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session scratch root for ALL helixgen state the suite may write."""
    root = tmp_path_factory.mktemp("helixgen-tui-live")
    (root / "home").mkdir()
    (root / "irs").mkdir()
    (root / "backups").mkdir()
    (root / "work").mkdir()
    # An explicitly-set $HELIXGEN_PREFS pointing at a missing file is an
    # error, so materialize an empty prefs file.
    (root / "preferences.json").write_text("{}\n")
    return root


@pytest.fixture(scope="session", autouse=True)
def _live_env(scratch: Path, real_library: Path):
    """Redirect ALL helixgen state to scratch, in os.environ, for the whole
    session — the in-process port under test and every CLI subprocess the
    safety net spawns must see the same isolated state."""
    # The suite's whole job is telling "the port broke" apart from "the engine
    # broke", so an engine below the pin (helixgen-core #38 healed the -11
    # listing cache on push, which `_wait_ir_registered` depends on) must fail
    # as itself, not as a TUI regression.
    engine = version("helixgen")
    # findall, not split(".") + int(): a pre-release like "0.31rc1" would raise
    # ValueError out of the gate itself instead of reaching the message below.
    if tuple(int(p) for p in re.findall(r"\d+", engine)[:2]) < (0, 31):
        pytest.fail(
            f"live suite needs helixgen >=0.31 (installed: {engine}) — below "
            "that, a pushed IR never re-appears in list-irs (core #38) and the "
            "IR tests fail as if the TUI regressed. Re-sync the venv."
        )
    redirect = {
        "HELIXGEN_HOME": str(scratch / "home"),
        # The advisory-lock root stays REAL (it would otherwise derive from
        # the redirected home): the session lease exists to exclude OTHER
        # helixgen processes on this machine. See the module docstring.
        "HELIXGEN_LOCKS": str(_REAL_LOCKS),
        "HELIXGEN_SETLISTS": str(scratch / "setlists.json"),
        "HELIXGEN_DEVICE_SLOTS": str(scratch / "device-slots.json"),
        "HELIXGEN_IRS": str(scratch / "irs"),
        "HELIXGEN_IRHASH_CACHE": str(scratch / "irhash-cache.json"),
        "HELIXGEN_DEVICE_BACKUPS": str(scratch / "backups"),
        "HELIXGEN_PREFS": str(scratch / "preferences.json"),
        "HELIXGEN_LIBRARY": str(real_library),
        # The suite holds the real machine-local `all` lease (`cli` fixture);
        # this token lets its own verbs and CLI calls pass through it.
        "HELIXGEN_LOCK_TOKEN": f"tui-live-suite-{uuid.uuid4().hex}",
    }
    if DEVICE_IP:
        # Pin the pre-redirect resolution: the scratch home has no device
        # records, so without this the offline-first hinge would fire.
        redirect["HELIXGEN_HELIX_IP"] = DEVICE_IP
    saved = {k: os.environ.get(k) for k in redirect}
    os.environ.update(redirect)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --------------------------------------------------------------------------
# engine CLI runner (safety net) + session device lease
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def cli(_live_env):
    """Run the SAME engine the port imports, as a CLI subprocess; returns
    (exit_code, stdout, stderr). Holds the real machine-local ``all`` device
    lease for the whole run (released at teardown)."""
    launcher = "from helixgen.cli import cli; cli()"

    def run(*args, timeout: float = 300):
        proc = subprocess.run(
            [sys.executable, "-c", launcher, *[str(a) for a in args]],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr

    if not DEVICE_IP:
        # Nothing to serialize against (every device-backed test skips), and
        # leases are keyed per-IP under the user's REAL lock root — a
        # fabricated address would leave junk there.
        yield run
        return
    # TTL sized to the run (minutes), not to a workday: the lease lives in the
    # real lock root and is only released in the finally below, so a SIGKILL
    # would otherwise wedge every other helixgen process on this machine until
    # it expires. Recover a wedged lease with `helixgen device unlock --force`.
    code, out, err = run(
        "device", "lock", "--scope", "all", "--label", "tui-live-suite",
        "--ttl", "1800", "--ip", DEVICE_IP,
    )
    assert code == 0, (
        "could not acquire the session 'all' device lease — is another "
        f"helixgen session holding the device? {err or out}"
    )
    try:
        yield run
    finally:
        # Never silent: the lease lives in the REAL lock root with a 1800s TTL,
        # so a failed release wedges every other helixgen process on this
        # machine for up to half an hour. Same visible-warning posture as the
        # other teardown helpers here.
        code, out, err = run("device", "unlock", "--ip", DEVICE_IP)
        if code != 0:
            print(
                "\n[tests/live] WARNING: could not release the session 'all' "
                f"device lease ({(err or out).strip()}) — it expires within "
                "1800s, or clear it now with `helixgen device unlock --force`"
            )


# --------------------------------------------------------------------------
# device gating + safety net
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def device() -> str:
    """Cheap reachability probe (the Stadium ignores ICMP — TCP-connect 2002)."""
    if not DEVICE_IP:
        pytest.skip(
            "no Helix IP configured — set HELIXGEN_HELIX_IP or run "
            "`helixgen device discover` once; device-backed live tests skipped"
        )
    try:
        with socket.create_connection((DEVICE_IP, DEVICE_PORT), timeout=3):
            pass
    except OSError as e:
        pytest.skip(
            f"Helix device unreachable at {DEVICE_IP}:{DEVICE_PORT} ({e}) — "
            "device-backed live tests skipped"
        )
    return DEVICE_IP


@pytest.fixture(scope="session")
def device_backup(device: str, cli, scratch: Path) -> Path:
    """Upfront safety backup of the user setlist, to scratch."""
    dest = scratch / "backups"
    code, out, err = cli("device", "backup", "--dir", dest, timeout=600)
    assert code == 0, f"upfront `device backup` failed: {err or out}"
    assert (dest / "manifest.json").exists()
    # `device backup` lists NON-strictly, so a dropped frame exits 0, writes a
    # manifest with zero entries, and `manifest.json exists` passes over a
    # restore point that restores nothing — an inert safety net, right before
    # the session starts installing/deleting/syncing on real hardware.
    # Cross-check against a STRICT listing (the only thing that tells a genuine
    # empty pool apart from a dropped reply): it raises rather than under-count.
    from helixgen.device import HelixClient

    with HelixClient(device, DEVICE_PORT) as h:
        on_device = h.list_presets(strict=True)
    backed_up = json.loads((dest / "manifest.json").read_text())["entries"]
    assert len(backed_up) == len(on_device), (
        f"upfront backup covers {len(backed_up)} preset(s) but the device has "
        f"{len(on_device)} — partial/empty backup (the engine's default "
        "listing reads a dropped frame as an empty list); re-run rather than "
        "mutate the device without a restore point"
    )
    return dest


def _normalize_rows(raw: str, *keys: str):
    # str() every field: a row missing a key yields None, and sorting tuples
    # that mix None with int/str raises TypeError — inside the teardown guard
    # that would replace the state-leak signal with an unrelated crash.
    return sorted(tuple(str(m.get(k)) for k in keys) for m in json.loads(raw))


def _capture_device_state(cli) -> dict:
    state = {}
    for key, args, keys in (
        ("presets_user", ("device", "list", "--json"), ("cid_", "name", "posi")),
        ("setlists", ("device", "setlists", "--json"), ("cid_", "name", "posi")),
        ("irs", ("device", "list-irs", "--json"), ("hash", "name", "posi")),
    ):
        code, out, err = cli(*args)
        assert code == 0, f"state capture {' '.join(args)} failed: {err or out}"
        state[key] = _normalize_rows(out, *keys)
    return state


def _sweep_stale_hgtest_artifacts(cli) -> list[str]:
    """Delete HGTEST-prefixed leftovers from a previously crashed run, BEFORE
    the state capture (a stale artifact must not be absorbed into the
    baseline). Only ever touches HGTEST-prefixed presets/setlists/IRs.

    A delete that FAILS is fatal: the leftover would be absorbed into the
    baseline, the teardown diff would then match, and the suite would report a
    clean device while its own junk sat on it."""
    swept, failed = [], []
    for kind, list_args, id_key, delete_args in (
        ("preset", ("device", "list", "--json"), "cid_", ("device", "delete")),
        ("setlist", ("device", "setlists", "--json"), "name", ("device", "setlist", "delete")),
        ("IR", ("device", "list-irs", "--json"), "hash", ("device", "delete-ir")),
    ):
        code, out, _ = cli(*list_args)
        if code != 0:
            continue
        for m in json.loads(out):
            name = m.get("name") or ""
            if not name.startswith(HGTEST):
                continue
            # ``.get``, not ``[...]``: a row missing its id key would raise a
            # KeyError out of a session fixture and replace the state-leak
            # signal with an unrelated traceback. An unidentifiable artifact
            # can't be swept, so it belongs in ``failed`` like any other.
            ident = m.get(id_key)
            label = f"{kind} {name!r} ({id_key}={ident!r})"
            if ident is None:
                failed.append(f"{label}: row has no {id_key!r} to delete by")
                continue
            code, out, err = cli(*delete_args, ident, "--yes")
            if code == 0:
                swept.append(label)
            else:
                failed.append(f"{label}: {(err or out).strip()}")
    assert not failed, (
        "could not sweep stale HGTEST artifacts from a previous run — they "
        "would poison the state baseline. Clean them by hand and re-run:\n  "
        + "\n  ".join(failed)
    )
    return swept


@pytest.fixture(scope="session")
def device_state_guard(device: str, device_backup: Path, cli) -> dict:
    """Capture device state up front; FAIL the session if it changed at the
    end. Normalized on (cid, name, posi) / (hash, name, posi). Every
    device-touching test depends on this (via ``helix``), so the capture
    precedes the first mutation and the check runs after the last cleanup."""
    swept = _sweep_stale_hgtest_artifacts(cli)
    if swept:
        print(
            f"\n[tests/live] swept stale HGTEST artifacts from a previous run: {', '.join(swept)}"
        )
    before = _capture_device_state(cli)
    yield before
    after = _capture_device_state(cli)
    assert after == before, (
        "DEVICE STATE CHANGED across the live suite — a test leaked an "
        "artifact or mutated non-HGTEST state.\n"
        + "\n".join(
            f"[{k}]\n  before: {before[k]}\n  after:  {after[k]}"
            for k in before
            if before[k] != after[k]
        )
    )


@pytest.fixture(scope="session")
def helix(device: str, device_state_guard: dict, cli):
    """The standard dependency for device-backed tests: probe + upfront
    backup + state guard, in that order. Returns the CLI runner."""
    return cli


@pytest.fixture(scope="session")
def real_port(helix):
    """The object under test: a ``RealDevicePort``, behind the full safety
    chain."""
    from helixgen_tui.core.real import RealDevicePort

    return RealDevicePort()

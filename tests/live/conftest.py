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

    HELIXGEN_TUI_LIVE=1 .venv/bin/python -m pytest tests/live -q

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
* The device IP is resolved BEFORE the home redirect (``$HELIXGEN_HELIX_IP``,
  else the newest ``~/.helixgen/devices/*.json`` record, stdlib-only — the
  same ordering as ``discovery.resolve_ip()``) and pinned into
  ``HELIXGEN_HELIX_IP``, because the scratch home has no device records.
* An upfront ``device backup`` (to scratch) runs before the first device test
  (``device_backup``).
* Device state (user presets / setlists / IRs, via the engine CLI's
  ``--json`` verbs) is captured before the first device test and re-captured
  at session teardown; the session ITSELF FAILS if the normalized state
  changed (``device_state_guard``). Stale ``HGTEST`` leftovers from a crashed
  previous run are swept before the capture. Known blind spots, stated
  honestly: the preset pool (cid space -2) cannot be listed directly, so pool
  leaks are only caught by the sync tests' own assertions; the ACTIVE edit
  buffer is not part of the diff (``make_active`` tests capture and restore
  the active preset themselves, but unsaved edit-buffer changes present
  before the run are discarded by design — saved presets are covered by the
  upfront backup).
* The repo-wide session guard in ``tests/conftest.py`` verifies the user's
  real ``~/.helixgen`` files (everything except the ``locks/`` subtree — see
  below) are untouched at teardown, by full mtime snapshot.
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
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

#: Every artifact the suite creates carries this prefix; teardown helpers
#: refuse to touch anything without it.
HGTEST = "HGTEST"

DEVICE_PORT = 2002
LIVE_ENABLED = os.environ.get("HELIXGEN_TUI_LIVE") == "1"

_LIVE_DIR = Path(__file__).resolve().parent
_REAL_HELIXGEN = Path.home() / ".helixgen"


def _persisted_device_ip() -> str | None:
    """The newest discovered ip across ~/.helixgen/devices/*.json, stdlib-only
    (the suite must resolve it BEFORE redirecting $HELIXGEN_HOME to scratch).
    Ordering matches ``discovery.resolve_ip()``: ``ip_updated_at`` desc, then
    ``serial`` desc (filename stem when the field is absent)."""
    home = Path(os.environ.get("HELIXGEN_HOME") or _REAL_HELIXGEN)
    best: tuple | None = None
    try:
        files = list((home / "devices").glob("*.json"))
    except OSError:
        return None
    for p in files:
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("ip"):
            continue
        key = (float(data.get("ip_updated_at") or 0.0), str(data.get("serial") or p.stem))
        if best is None or key > best[0]:
            best = (key, str(data["ip"]))
    return best[1] if best else None


DEVICE_IP = os.environ.get("HELIXGEN_HELIX_IP") or _persisted_device_ip()


def pytest_collection_modifyitems(config, items):
    """Mark everything under tests/live ``live``; hard-skip it all unless
    HELIXGEN_TUI_LIVE=1 (collection-time, so no fixture ever runs)."""
    skip = pytest.mark.skip(
        reason="live device suite is opt-in: set HELIXGEN_TUI_LIVE=1 "
        f"(device tests also need the Helix reachable on {DEVICE_IP}:{DEVICE_PORT})"
    )
    for item in items:
        if _LIVE_DIR not in Path(str(item.fspath)).parents:
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
    if sys.modules.get("helixgen") is None:
        pytest.importorskip("zmq", reason="live suite needs pyzmq for the device layer")
    redirect = {
        "HELIXGEN_HOME": str(scratch / "home"),
        # The advisory-lock root stays REAL (it would otherwise derive from
        # the redirected home): the session lease exists to exclude OTHER
        # helixgen processes on this machine. See the module docstring.
        "HELIXGEN_LOCKS": str(_REAL_HELIXGEN / "locks"),
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

    lock_ip = ("--ip", DEVICE_IP) if DEVICE_IP else ("--ip", "no-device")
    code, out, err = run(
        "device", "lock", "--scope", "all", "--label", "tui-live-suite", "--ttl", "7200", *lock_ip
    )
    assert code == 0, (
        "could not acquire the session 'all' device lease — is another "
        f"helixgen session holding the device? {err or out}"
    )
    try:
        yield run
    finally:
        run("device", "unlock", *lock_ip)


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
    return dest


def _normalize_rows(raw: str, *keys: str):
    return sorted(tuple(m.get(k) for k in keys) for m in json.loads(raw))


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
    baseline). Only ever touches HGTEST-prefixed presets/setlists/IRs."""
    swept = []
    code, out, _ = cli("device", "list", "--json")
    if code == 0:
        for m in json.loads(out):
            if (m.get("name") or "").startswith(HGTEST):
                cli("device", "delete", m["cid_"], "--yes")
                swept.append(f"preset {m['name']!r} (cid {m['cid_']})")
    code, out, _ = cli("device", "setlists", "--json")
    if code == 0:
        for m in json.loads(out):
            if (m.get("name") or "").startswith(HGTEST):
                cli("device", "setlist", "delete", m["name"], "--yes")
                swept.append(f"setlist {m['name']!r}")
    code, out, _ = cli("device", "list-irs", "--json")
    if code == 0:
        for m in json.loads(out):
            if (m.get("name") or "").startswith(HGTEST):
                cli("device", "delete-ir", m["hash"], "--yes")
                swept.append(f"IR {m['name']!r} ({m['hash']})")
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

"""Task 2: read/status + plan-only verbs of ``RealDevicePort`` on hardware,
asserting the shapes the TUI consumes (``DeviceStateVM``, ``IrVM``,
``MutationPlan``) — plus the offline-first hinge under real conditions.

Reference values are never hardcoded; shapes and invariants only (the IR list
is cross-checked against the engine CLI's own ``list-irs`` so a port/engine
skew shows up as a diff, not a guess).
"""

from __future__ import annotations

import json
import os
import socket

import pytest

from helixgen_tui.core.models import DeviceStateVM, IrVM, MutationPlan
from helixgen_tui.core.ports import DeviceUnreachable
from helixgen_tui.core.real import RealDevicePort

# --------------------------------------------------------------------------
# read / status, device-backed
# --------------------------------------------------------------------------


def test_probe_shape(real_port):
    vm = real_port.probe()
    assert isinstance(vm, DeviceStateVM)
    assert vm.status == "connected"
    # _live_env pinned the pre-redirect resolution into the environment
    assert vm.address == os.environ["HELIXGEN_HELIX_IP"]
    assert vm.model and isinstance(vm.model, str)
    assert vm.detail == ""
    # active_tone is advisory: None or a non-empty name
    assert vm.active_tone is None or (isinstance(vm.active_tone, str) and vm.active_tone)


def test_info_shape(real_port):
    info = real_port.info()
    assert isinstance(info, dict) and info
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in info.items())
    # real /getProductInfo values, same bar as core's live suite
    for key in ("model", "firmware", "serial"):
        assert info.get(key), (key, info)


def test_list_device_irs_matches_engine_cli(real_port, helix):
    irs = real_port.list_device_irs()
    assert isinstance(irs, list)
    for ir in irs:
        assert isinstance(ir, IrVM)
        assert ir.name and isinstance(ir.name, str)
        assert ir.on_device is True
        assert ir.pack is None
    code, out, err = helix("device", "list-irs", "--json")
    assert code == 0, err or out
    cli_hashes = {m.get("hash") for m in json.loads(out)}
    assert {ir.irhash for ir in irs} == cli_hashes


def test_lock_status_shows_session_lease(real_port):
    leases = real_port.lock_status()
    assert isinstance(leases, list)
    assert all(isinstance(s, str) for s in leases)
    # the cli fixture holds the machine-local 'all' lease for the whole run
    assert any("tui-live-suite" in s for s in leases), leases


# --------------------------------------------------------------------------
# plan-only verbs (never mutate; plan_prune_irs talks to the device)
# --------------------------------------------------------------------------


def _assert_plan(plan: MutationPlan):
    assert isinstance(plan, MutationPlan)
    assert plan.title and isinstance(plan.title, str)
    assert isinstance(plan.lines, tuple) and plan.lines
    assert all(isinstance(line, str) and line for line in plan.lines)


def test_plan_sync_all(real_port):
    plan = real_port.plan_sync_all(gc=False)
    _assert_plan(plan)
    gc_plan = real_port.plan_sync_all(gc=True)
    _assert_plan(gc_plan)
    assert len(gc_plan.lines) == len(plan.lines) + 1  # the GC line


def test_plan_delete_tone(real_port):
    plan = real_port.plan_delete_tone("HGTEST nonexistent")
    _assert_plan(plan)
    assert "HGTEST nonexistent" in " ".join(plan.lines)


def test_plan_delete_ir(real_port):
    plan = real_port.plan_delete_ir("HGTEST nonexistent")
    _assert_plan(plan)
    assert "HGTEST nonexistent" in " ".join(plan.lines)


def test_plan_prune_irs_matches_engine_cli(real_port, helix):
    """Shape alone can't catch key skew here: the plan feeds a DESTRUCTIVE
    confirm modal, and reading a key the engine doesn't emit yields a
    well-formed "(nothing to prune)" plan while the confirm deletes for real
    (that exact bug shipped). Cross-check against the engine's own dry run."""
    plan = real_port.plan_prune_irs()
    _assert_plan(plan)
    code, out, err = helix("device", "ir-prune", "--json", timeout=300)
    assert code == 0, err or out
    orphans = json.loads(out).get("orphans") or []
    joined = " ".join(plan.lines)
    if orphans:
        for o in orphans:
            assert str(o.get("name") or o.get("hash")) in joined, (orphans, plan.lines)
    else:
        assert "no unreferenced device IRs" in joined, plan.lines


def test_plan_restore_is_unsupported(real_port):
    plan = real_port.plan_restore("whatever.json")
    _assert_plan(plan)
    assert "restore" in plan.lines[0]


# --------------------------------------------------------------------------
# offline-first hinge, real conditions (env gate only — no device needed)
# --------------------------------------------------------------------------


def test_probe_unconfigured_raises_without_socket(monkeypatch):
    """No --ip, no $HELIXGEN_HELIX_IP, no device record (scratch home):
    DeviceUnreachable immediately, and provably no socket."""
    monkeypatch.delenv("HELIXGEN_HELIX_IP", raising=False)

    def _bomb(*a, **k):  # any socket construction = the hinge leaked a connect
        raise AssertionError("offline probe opened a socket")

    monkeypatch.setattr(socket, "socket", _bomb)
    monkeypatch.setattr(socket, "create_connection", _bomb)
    with pytest.raises(DeviceUnreachable):
        RealDevicePort().probe()
    assert RealDevicePort().lock_status() == []


def test_probe_unreachable_maps_to_device_unreachable(monkeypatch):
    """Configured-but-unreachable (real network stack, closed local port):
    the failure maps to DeviceUnreachable instead of escaping raw."""
    with socket.socket() as s:  # a port that is definitely closed
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
    monkeypatch.setenv("HELIXGEN_HELIX_IP", "127.0.0.1")
    with pytest.raises(DeviceUnreachable):
        RealDevicePort(port=closed_port).probe()

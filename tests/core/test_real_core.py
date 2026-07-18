"""build_core() wiring: real library/setlists + the offline-first RealDevicePort.

Every test here forces the OFFLINE state (no device record, and the ambient
``$HELIXGEN_HELIX_IP`` is deleted so a dev machine pointed at the real Helix
can't leak a connection). The networked verbs are checked only for their
offline behavior and their signatures — never driven against hardware.
"""

from __future__ import annotations

import inspect

import pytest

from helixgen_tui.core.models import DeviceStateVM, IrVM, MutationPlan, OpResult
from helixgen_tui.core.ports import Core, DevicePort, DeviceUnreachable
from helixgen_tui.core.real import RealDevicePort, build_core


@pytest.fixture
def offline(tmp_home, monkeypatch):
    """tmp_home with no discovered device and no HELIXGEN_HELIX_IP — resolve_ip
    raises immediately, so nothing can open a socket."""
    monkeypatch.delenv("HELIXGEN_HELIX_IP", raising=False)
    return tmp_home


def test_build_core_satisfies_core_protocol(offline):
    core = build_core()
    assert isinstance(core, Core)
    assert isinstance(core.device, RealDevicePort)
    assert isinstance(core.device, DevicePort)  # runtime_checkable: all verbs present


def test_real_device_port_matches_protocol_signatures():
    """Signature-level conformance (no calls): every DevicePort method exists on
    RealDevicePort with the same parameter names."""
    for name, proto_member in inspect.getmembers(DevicePort, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        impl = getattr(RealDevicePort, name, None)
        assert impl is not None, f"RealDevicePort missing {name}"
        proto_params = list(inspect.signature(proto_member).parameters)
        impl_params = list(inspect.signature(impl).parameters)
        assert impl_params == proto_params, f"{name}: {impl_params} != {proto_params}"


def test_list_local_irs_empty_home(offline):
    assert build_core().list_local_irs() == []


def test_probe_offline_raises_device_unreachable(offline):
    with pytest.raises(DeviceUnreachable):
        build_core().device.probe()


def test_make_active_offline_raises_device_unreachable(offline):
    # resolve_ip fails before any socket is opened.
    with pytest.raises(DeviceUnreachable):
        build_core().device.make_active("some-tone")


def test_sync_tone_not_in_any_setlist_is_soft_failure(offline):
    # Empty manifest -> the tone is in no setlist, so we refuse without a device.
    result = build_core().device.sync_tone("orphan-tone")
    assert result.ok is False
    assert "setlist" in result.message


def test_lock_status_offline_is_empty(offline):
    assert build_core().device.lock_status() == []


def test_restore_reports_cid_gap_without_device(offline):
    result = build_core().device.restore("backup.sbe")
    assert result.ok is False
    assert "cid" in result.message


def test_delete_tone_is_not_wired_yet(offline):
    result = build_core().device.delete_tone("t")
    assert result.ok is False


def test_plans_are_offline_and_well_formed(offline):
    device = build_core().device
    assert isinstance(device.plan_sync_all(gc=False), MutationPlan)
    assert isinstance(device.plan_delete_tone("t"), MutationPlan)
    assert isinstance(device.plan_restore("f"), MutationPlan)
    assert isinstance(device.plan_delete_ir("ir"), MutationPlan)


def test_device_state_vm_and_irvm_types_are_importable():
    # Guards the module's typed surface without touching a device.
    assert DeviceStateVM and IrVM and OpResult

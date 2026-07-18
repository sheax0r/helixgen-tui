"""View models are pure data: frozen, and SyncState values round-trip."""

import dataclasses

import pytest

from helixgen_tui.core.models import (
    DeviceStateVM,
    IrVM,
    MutationPlan,
    OpResult,
    SetlistVM,
    SyncState,
    ToneVM,
)


def test_sync_state_values_round_trip():
    assert SyncState("synced") is SyncState.SYNCED
    assert SyncState("local") is SyncState.LOCAL_ONLY
    assert SyncState("unknown") is SyncState.UNKNOWN
    assert SyncState.SYNCED.value == "synced"
    assert SyncState.LOCAL_ONLY.value == "local"
    assert SyncState.UNKNOWN.value == "unknown"


def test_tone_vm_is_frozen():
    vm = ToneVM(
        name="Lead",
        tone_id="abc123",
        guitar="Strat",
        description=None,
        sync=SyncState.SYNCED,
        setlists=("Gig 1",),
    )
    assert vm.name == "Lead"
    with pytest.raises(dataclasses.FrozenInstanceError):
        vm.name = "Other"


def test_setlist_vm_is_frozen():
    vm = SetlistVM(name="Gig 1", sync_enabled=True, tones=("Lead", "Rhythm"))
    assert vm.tones == ("Lead", "Rhythm")
    with pytest.raises(dataclasses.FrozenInstanceError):
        vm.sync_enabled = False


def test_ir_vm_is_frozen():
    vm = IrVM(name="Cab A", pack="Factory", irhash="deadbeef", on_device=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        vm.on_device = False


def test_ir_vm_on_device_none_means_unknown():
    vm = IrVM(name="Cab A", pack=None, irhash=None, on_device=None)
    assert vm.on_device is None


def test_device_state_vm_is_frozen():
    vm = DeviceStateVM(
        status="offline", model=None, address=None, active_tone=None, detail="device: offline"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        vm.status = "connected"


def test_mutation_plan_is_frozen():
    vm = MutationPlan(title="Sync all", lines=("line1", "line2"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        vm.title = "Other"


def test_op_result_is_frozen():
    vm = OpResult(ok=True, message="ok")
    assert vm.ok is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        vm.ok = False

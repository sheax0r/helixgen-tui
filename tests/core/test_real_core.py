"""build_core() wiring: real library/setlists + the NullDevicePort placeholder."""

from __future__ import annotations

import pytest

from helixgen_tui.core.models import OpResult
from helixgen_tui.core.ports import Core, DeviceUnreachable
from helixgen_tui.core.real import NullDevicePort, build_core


def test_build_core_satisfies_core_protocol(tmp_home):
    core = build_core()
    assert isinstance(core, Core)
    assert isinstance(core.device, NullDevicePort)


def test_list_local_irs_empty_home(tmp_home):
    assert build_core().list_local_irs() == []


def test_null_device_probe_raises_device_unreachable(tmp_home):
    with pytest.raises(DeviceUnreachable, match="no device configured"):
        build_core().device.probe()


def test_null_device_op_methods_return_placeholder_failure(tmp_home):
    device = build_core().device
    expected = OpResult(ok=False, message="device support arrives in a later task")
    assert device.make_active("t") == expected
    assert device.sync_tone("t") == expected
    assert device.sync_setlist("s", gc=False) == expected
    assert device.sync_all(gc=True) == expected
    assert device.delete_tone("t") == expected
    assert device.push_ir("ir") == expected
    assert device.delete_ir("ir") == expected
    assert device.prune_irs() == expected
    assert device.rename_ir("a", "b") == expected
    assert device.backup() == expected
    assert device.restore("f") == expected

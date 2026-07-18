"""Import-boundary guard: only helixgen_tui/core/ may import the `helixgen` package.

Also carries the FakeCore self-test (the test double is exercised here because
it has no other dedicated test module: mutations append to `.calls`, and
`fail_next` raises `DeviceUnreachable` exactly once, then clears itself).
"""

import pathlib
import re

import pytest

from helixgen_tui.core.models import DeviceStateVM
from helixgen_tui.core.ports import DeviceUnreachable

from fake_core import FakeCore, FakeDevicePort

SRC = pathlib.Path(__file__).parent.parent / "src" / "helixgen_tui"


def test_only_core_imports_helixgen():
    offenders = [
        p
        for p in SRC.rglob("*.py")
        if "core" not in p.parts
        and re.search(r"^\s*(import|from)\s+helixgen\b", p.read_text(), re.M)
    ]
    assert offenders == []


def test_fake_device_port_records_mutations_in_calls():
    device = FakeDevicePort()
    result = device.make_active("tone-1")
    assert result.ok is True
    assert result.message == "make_active ok"
    assert device.calls == [("make_active", ("tone-1",))]

    device.sync_setlist("Gig 1", True)
    assert device.calls[-1] == ("sync_setlist", ("Gig 1", True))


def test_fake_device_port_fail_next_raises_once_then_clears():
    device = FakeDevicePort(fail_next=True)
    with pytest.raises(DeviceUnreachable):
        device.make_active("tone-1")
    assert device.fail_next is False
    assert device.calls == []

    # the flag has cleared: the next call succeeds normally.
    result = device.make_active("tone-1")
    assert result.ok is True
    assert device.calls == [("make_active", ("tone-1",))]


def test_fake_device_port_fail_next_applies_to_reads_too():
    device = FakeDevicePort(fail_next=True)
    with pytest.raises(DeviceUnreachable):
        device.probe()
    assert device.fail_next is False
    assert device.probe() == device.state


def test_fake_core_defaults_are_empty_and_device_is_offline():
    core = FakeCore()
    assert core.library.list_tones() == []
    assert core.setlists.list_setlists() == []
    assert core.list_local_irs() == []
    assert isinstance(core.device, FakeDevicePort)
    assert core.device.state == DeviceStateVM(
        status="offline",
        model=None,
        address=None,
        active_tone=None,
        detail="device: ○ offline",
    )


def test_fake_core_setlist_port_records_mutations():
    core = FakeCore()
    result = core.setlists.add_tone("Gig 1", "tone-1")
    assert result.ok is True
    assert core.setlists.calls == [("add_tone", ("Gig 1", "tone-1"))]

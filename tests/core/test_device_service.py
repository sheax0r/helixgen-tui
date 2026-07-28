"""DeviceService: probe loop, offline short-circuit, timeout, unreachable flips.

Pure-Python — a synchronous ``spawn`` runs the service's work inline, so every
scenario is deterministic with no event loop. The one timeout scenario uses the
real default (daemon-thread) spawn with a tiny timeout and a sleeping fn, and
stays well under a second. No real device is ever contacted.
"""

from __future__ import annotations

import time

from helixgen_tui.core.device import DeviceService, QueryResult
from helixgen_tui.core.models import DeviceStateVM, IrVM, OpResult
from fake_core import FakeDevicePort

_CONNECTED = DeviceStateVM(
    status="connected",
    model="Helix Stadium",
    address="192.168.4.2",
    active_tone="Foo - Bar",
    detail="",
)


def _sync_spawn(fn):
    fn()


def _service(port, **kw):
    states: list[DeviceStateVM] = []
    svc = DeviceService(port, on_state=states.append, spawn=_sync_spawn, **kw)
    return svc, states


def test_probe_success_reports_connected_state():
    svc, states = _service(FakeDevicePort(state=_CONNECTED))
    svc.retry_now()
    assert states[-1] == _CONNECTED
    assert svc.state == _CONNECTED
    assert svc.state.status == "connected"


def test_probe_unreachable_reports_offline_state():
    port = FakeDevicePort(state=_CONNECTED, fail_next=True)  # probe raises once
    svc, states = _service(port)
    svc.retry_now()
    assert states[-1].status == "offline"
    assert svc.state.status == "offline"


def test_probe_non_connect_failure_reports_offline_with_the_reason():
    """A probe raising anything other than DeviceUnreachable (a protocol fault
    on a reachable device, or a bug in the port itself) must not silently kill
    the poller thread — but it must also not present as a bare "offline",
    indistinguishable from a device that is simply off the LAN. The reason
    rides `detail`, which the footer renders."""

    class _BrokenProbePort(FakeDevicePort):
        def probe(self):
            raise TypeError("probe() got an unexpected keyword argument 'strict'")

    svc, states = _service(_BrokenProbePort(state=_CONNECTED))
    svc.retry_now()
    assert states[-1].status == "offline"
    assert "unexpected keyword argument" in states[-1].detail


def test_run_while_offline_short_circuits_without_touching_port():
    port = FakeDevicePort()  # default offline state
    svc, _ = _service(port)
    svc.retry_now()  # confirms offline
    assert svc.state.status == "offline"

    results: list[OpResult] = []
    svc.run("make_active", lambda: port.make_active("t"), results.append)

    assert results == [OpResult(ok=False, message="device offline")]
    assert port.calls == []  # the port was never touched


def test_run_unreachable_mid_call_flips_state_offline():
    port = FakeDevicePort(state=_CONNECTED)
    svc, states = _service(port)
    svc.retry_now()
    assert svc.state.status == "connected"

    port.fail_next = True  # the next port call raises DeviceUnreachable
    results: list[OpResult] = []
    svc.run("make_active", lambda: port.make_active("t"), results.append)

    assert results and results[-1].ok is False
    assert svc.state.status == "offline"
    assert states[-1].status == "offline"


def test_run_timeout_yields_failure_with_timed_out_message():
    port = FakeDevicePort(state=_CONNECTED)
    # Real default (daemon-thread) spawn + a tiny timeout + a sleeping fn.
    states: list[DeviceStateVM] = []
    svc = DeviceService(port, on_state=states.append, timeout=0.01)
    # Force the service online without a spawn indirection: seed state directly.
    svc._state = _CONNECTED  # noqa: SLF001 — test drives the online precondition

    results: list[OpResult] = []
    done = []

    def _done(r):
        results.append(r)
        done.append(True)

    def _slow():
        time.sleep(1.0)
        return OpResult(ok=True, message="never")

    svc.run("make_active", _slow, _done)

    deadline = time.monotonic() + 0.9
    while not done and time.monotonic() < deadline:
        time.sleep(0.005)

    assert results, "done callback was never invoked"
    assert results[-1].ok is False
    assert "timed out" in results[-1].message


# -- query(): arbitrary-value reads (Task 7 fix) -----------------------------


def test_query_success_delivers_value():
    irs = [IrVM(name="Cab", pack=None, irhash="deadbeef", on_device=True)]
    port = FakeDevicePort(state=_CONNECTED, device_irs=irs)
    svc, _ = _service(port)
    svc.retry_now()
    assert svc.state.status == "connected"

    results: list[QueryResult] = []
    svc.query("list_device_irs", port.list_device_irs, results.append)

    assert results == [QueryResult(ok=True, value=irs, message="")]


def test_query_while_offline_short_circuits_without_touching_port():
    port = FakeDevicePort()  # default offline state
    svc, _ = _service(port)
    svc.retry_now()  # confirms offline
    assert svc.state.status == "offline"

    touched: list[bool] = []

    def _fn():
        touched.append(True)
        return port.list_device_irs()

    results: list[QueryResult] = []
    svc.query("list_device_irs", _fn, results.append)

    assert results == [QueryResult(ok=False, value=None, message="device offline")]
    assert touched == []  # the read was never called


def test_query_unreachable_mid_call_flips_state_offline():
    port = FakeDevicePort(state=_CONNECTED)
    svc, states = _service(port)
    svc.retry_now()
    assert svc.state.status == "connected"

    port.fail_next = True  # the next port call raises DeviceUnreachable
    results: list[QueryResult] = []
    svc.query("list_device_irs", port.list_device_irs, results.append)

    assert results and results[-1].ok is False
    assert results[-1].value is None
    assert svc.state.status == "offline"
    assert states[-1].status == "offline"


def test_query_timeout_yields_failure_with_timed_out_message():
    port = FakeDevicePort(state=_CONNECTED)
    # Real default (daemon-thread) spawn + a tiny timeout + a sleeping fn.
    states: list[DeviceStateVM] = []
    svc = DeviceService(port, on_state=states.append, timeout=0.01)
    svc._state = _CONNECTED  # noqa: SLF001 — test drives the online precondition

    results: list[QueryResult] = []
    done: list[bool] = []

    def _done(r):
        results.append(r)
        done.append(True)

    def _slow():
        time.sleep(1.0)
        return ["never"]

    svc.query("list_device_irs", _slow, _done)

    deadline = time.monotonic() + 0.9
    while not done and time.monotonic() < deadline:
        time.sleep(0.005)

    assert results, "done callback was never invoked"
    assert results[-1].ok is False
    assert results[-1].value is None
    assert "timed out" in results[-1].message


def test_run_timeout_reports_failure_while_the_write_still_lands():
    """Backlog #26's dangerous half: the timeout is a JOIN, not a cancel.

    ``_call_guarded`` starts a daemon thread and gives up waiting after
    ``timeout``; nothing stops the thread. So a mutating verb slower than the
    join reports ``"<label>: timed out"`` to the footer and then completes
    anyway — a false failure over a write that lands. Measured on hardware
    2026-07-28: ``plan_prune_irs`` takes 51.4s against the 5s default, so the
    app's Prune flow hits this every time.
    """
    port = FakeDevicePort(state=_CONNECTED)
    svc = DeviceService(port, on_state=lambda _s: None, timeout=0.01)
    svc._state = _CONNECTED  # noqa: SLF001 — test drives the online precondition

    landed: list[str] = []
    results: list[OpResult] = []

    def _slow_write() -> OpResult:
        time.sleep(0.2)
        landed.append("device mutated")  # the write the user was told failed
        return OpResult(ok=True, message="pruned")

    svc.run("Prune", _slow_write, results.append)

    deadline = time.monotonic() + 0.9
    while not results and time.monotonic() < deadline:
        time.sleep(0.005)
    assert results, "done callback was never invoked"
    assert results[-1].ok is False
    assert "timed out" in results[-1].message
    assert not landed, "precondition: the write had not finished at report time"

    deadline = time.monotonic() + 0.9
    while not landed and time.monotonic() < deadline:
        time.sleep(0.005)
    assert landed == ["device mutated"], (
        "the worker was abandoned, not cancelled — the write lands after the "
        "failure is reported"
    )

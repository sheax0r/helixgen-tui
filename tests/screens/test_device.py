"""Pilot tests for DeviceScreen: info, backup, restore, lock status, retry."""

from __future__ import annotations

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import DeviceStateVM
from helixgen_tui.screens.device import RestorePathModal
from helixgen_tui.widgets.confirm_modal import ConfirmModal
from helixgen_tui.widgets.status_footer import StatusFooter

from fake_core import FakeCore, FakeDevicePort

_CONNECTED = DeviceStateVM(
    status="connected",
    model="Helix Stadium",
    address="192.168.4.2",
    active_tone="AC/DC - Back in Black",
    detail="",
)


class _InfoDevicePort(FakeDevicePort):
    """FakeDevicePort with scriptable info()/lock_status() payloads."""

    def __init__(self, *, info=None, locks=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._info = dict(info) if info is not None else {}
        self._locks = list(locks) if locks is not None else []

    def info(self):
        self._check_fail()
        return dict(self._info)

    def lock_status(self):
        self._check_fail()
        return list(self._locks)


def _sync_spawn(fn):
    fn()


def _device_app(port):
    core = FakeCore(device=port)
    return HelixgenTuiApp(core, device_spawn=_sync_spawn)


async def test_offline_shows_info_placeholder():
    app = _device_app(FakeDevicePort())  # default offline
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        info_text = str(app.screen.query_one("#device-info").render())
        assert "offline" in info_text.lower()


async def test_offline_backup_refused_without_touching_port():
    port = FakeDevicePort()  # default offline
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert port.calls == []
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.last_action.lower()


async def test_connected_info_rows_and_active_tone_render():
    port = _InfoDevicePort(state=_CONNECTED, info={"Firmware": "3.50", "Serial": "ABC123"})
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        info_text = str(app.screen.query_one("#device-info").render())
        assert "Firmware: 3.50" in info_text
        assert "Serial: ABC123" in info_text
        assert "AC/DC - Back in Black" in info_text


async def test_backup_calls_port_and_footer_shows_result():
    port = _InfoDevicePort(state=_CONNECTED)
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert ("backup", ()) in port.calls
        footer = app.screen.query_one(StatusFooter)
        assert "backup ok" in footer.last_action


async def test_restore_flow_shows_plan_then_calls_restore_on_confirm():
    port = _InfoDevicePort(state=_CONNECTED)
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, RestorePathModal)

        for char in "/tmp/backup.hlx":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmModal)
        modal_text = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "/tmp/backup.hlx" in modal_text

        await pilot.press("y")
        await pilot.pause()
        assert ("restore", ("/tmp/backup.hlx",)) in port.calls


async def test_restore_flow_cancel_at_confirm_does_not_restore():
    port = _InfoDevicePort(state=_CONNECTED)
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        for char in "/tmp/backup.hlx":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)

        await pilot.press("n")
        await pilot.pause()
        assert port.calls == []


async def test_restore_offline_refused_without_opening_modal():
    port = FakeDevicePort()  # default offline
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert not isinstance(app.screen, RestorePathModal)
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.last_action.lower()


async def test_lock_status_lines_render_on_l():
    port = _InfoDevicePort(state=_CONNECTED, locks=["locked: tone edit", "locked: preset sync"])
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        locks_text = str(app.screen.query_one("#device-locks").render())
        assert "locked: tone edit" in locks_text
        assert "locked: preset sync" in locks_text


async def test_retry_reconnects_and_refreshes_info():
    port = FakeDevicePort()  # starts offline
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        info_text = str(app.screen.query_one("#device-info").render())
        assert "offline" in info_text.lower()

        port.state = _CONNECTED
        await pilot.press("r")
        await pilot.pause()

        info_text = str(app.screen.query_one("#device-info").render())
        assert "AC/DC - Back in Black" in info_text


# --- markup safety (#12): bracket-bearing device strings render literally ---


async def test_bracketed_active_tone_renders_literally_without_crashing():
    """A device active-tone name carrying markup brackets must render verbatim
    in the info panel, never be stripped or raise MarkupError (which would
    crash the screen)."""
    state = DeviceStateVM(
        status="connected",
        model="Helix Stadium",
        address="192.168.4.2",
        active_tone="Weird [/] Tone",
        detail="",
    )
    port = _InfoDevicePort(state=state, info={"Model [x]": "Stadium [b]"})
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        info_text = str(app.screen.query_one("#device-info").render())
        assert "Weird [/] Tone" in info_text
        assert "Model [x]: Stadium [b]" in info_text


async def test_bracketed_lock_label_renders_literally_without_crashing():
    """A lock label carrying markup brackets must render verbatim, not crash."""
    port = _InfoDevicePort(state=_CONNECTED, locks=["locked: [reverb]", "held by [/]"])
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        locks_text = str(app.screen.query_one("#device-locks").render())
        assert "locked: [reverb]" in locks_text
        assert "held by [/]" in locks_text


# --- real thread-worker spawn: the class of bug the fix addresses ----------


async def _wait_until(pilot, cond, timeout=3.0):
    """Pump the event loop until ``cond()`` holds (or fail after ``timeout``)."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await pilot.pause()
        if cond():
            return
    raise AssertionError("condition not met within timeout")


async def test_info_refresh_under_real_thread_spawn_renders_without_crashing():
    """``_refresh_info`` must marshal the ``info`` query's result back to the
    UI thread: under the REAL Textual thread-worker spawn, DeviceService.query's
    ``done`` callback runs off-thread, so updating the info Static directly
    from there would corrupt Textual's UI state instead of just failing a
    synchronous-spawn test."""
    port = _InfoDevicePort(state=_CONNECTED, info={"Firmware": "3.50", "Serial": "ABC123"})
    core = FakeCore(device=port)
    app = HelixgenTuiApp(core)  # default (real Textual thread-worker) spawn
    async with app.run_test() as pilot:
        await pilot.press("4")
        await _wait_until(
            pilot,
            lambda: (
                app.device_service is not None and app.device_service.state.status == "connected"
            ),
        )

        info_widget = app.screen.query_one("#device-info")
        await _wait_until(pilot, lambda: "Firmware: 3.50" in str(info_widget.render()))

        info_text = str(info_widget.render())
        assert "Serial: ABC123" in info_text
        assert "AC/DC - Back in Black" in info_text


# --- Fix 4: device info re-read on screen-resume ---------------------------


async def test_screen_resume_rereads_device_info():
    port = _InfoDevicePort(state=_CONNECTED, info={"Firmware": "3.50"})
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        assert "Firmware: 3.50" in str(app.screen.query_one("#device-info").render())
        await pilot.press("1")  # away to library
        await pilot.pause()
        port._info = {"Firmware": "3.70"}
        await pilot.press("4")  # back — on_screen_resume re-reads info
        await pilot.pause()
        assert "Firmware: 3.70" in str(app.screen.query_one("#device-info").render())

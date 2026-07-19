"""Pilot tests for IrsScreen: local/device panes, push, rename, delete, prune."""

from __future__ import annotations

import re

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import DeviceStateVM, IrVM, MutationPlan
from helixgen_tui.widgets.confirm_modal import ConfirmModal
from helixgen_tui.widgets.status_footer import StatusFooter
from textual.widgets import DataTable, Input

from fake_core import FakeCore, FakeDevicePort

_LOCAL_IRS = [
    IrVM(name="V30 Cab", pack="Factory", irhash="deadbeefcafef00d", on_device=None),
    IrVM(name="Greenback", pack="Factory", irhash="0123456789abcdef", on_device=None),
]

_DEVICE_IRS = [
    IrVM(name="V30 Cab", pack=None, irhash="deadbeefcafef00d", on_device=True),
]

_CONNECTED = DeviceStateVM(
    status="connected",
    model="Helix Stadium",
    address="192.168.4.2",
    active_tone=None,
    detail="",
)


def _sync_spawn(fn):
    fn()


def _app(device_irs=None, state=None, local_irs=None, fail_next=False):
    port = FakeDevicePort(
        state=state if state is not None else _CONNECTED,
        device_irs=device_irs if device_irs is not None else list(_DEVICE_IRS),
        fail_next=fail_next,
    )
    core = FakeCore(local_irs=list(_LOCAL_IRS) if local_irs is None else local_irs, device=port)
    return HelixgenTuiApp(core, device_spawn=_sync_spawn), port


def _rendered(table: DataTable) -> str:
    return "\n".join(
        str(table.get_cell_at((row, col)))
        for row in range(table.row_count)
        for col in range(len(table.columns))
    )


async def test_local_pane_lists_local_irs_while_offline():
    port_offline = FakeDevicePort()  # default offline
    core = FakeCore(local_irs=list(_LOCAL_IRS), device=port_offline)
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        assert local_table.row_count == 2
        rendered = _rendered(local_table)
        assert "V30 Cab" in rendered
        assert "Greenback" in rendered
        assert "Factory" in rendered
        assert "deadbeef" in rendered  # truncated hash (first 8 hex chars)
        assert "deadbeefcafef00d" not in rendered  # not the full hash


async def test_device_pane_shows_offline_placeholder_when_disconnected():
    port = FakeDevicePort()  # default offline
    core = FakeCore(local_irs=list(_LOCAL_IRS), device=port)
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        placeholder_text = "\n".join(
            str(w.render()) for w in app.screen.query("#irs-device-placeholder")
        )
        assert "unavailable" in placeholder_text
        assert "device offline" in placeholder_text
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        assert device_table.display is False


async def test_device_pane_lists_device_irs_when_connected():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        assert device_table.display is True
        assert device_table.row_count == 1
        rendered = _rendered(device_table)
        assert "V30 Cab" in rendered
        placeholder = app.screen.query_one("#irs-device-placeholder")
        assert placeholder.display is False


async def test_no_slot_addresses_rendered():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        rendered = _rendered(local_table) + "\n" + _rendered(device_table)
        assert re.search(r"\b[1-8][A-D]\b", rendered) is None


async def test_p_pushes_selected_local_ir():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        local_table.focus()
        await pilot.pause()
        await pilot.press("p")  # cursor row 0 = V30 Cab
        await pilot.pause()
        assert ("push_ir", ("deadbeefcafef00d",)) in port.calls
        footer = app.screen.query_one(StatusFooter)
        assert "push_ir ok" in footer.last_action


async def test_p_offline_refuses_without_touching_port():
    port = FakeDevicePort()  # default offline
    core = FakeCore(local_irs=list(_LOCAL_IRS), device=port)
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        local_table.focus()
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert port.calls == []
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.last_action.lower()


async def test_d_shows_plan_then_y_deletes():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        device_table.focus()
        await pilot.pause()
        await pilot.press("d")  # cursor row 0 = V30 Cab
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        modal_text = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "V30 Cab" in modal_text  # FakeDevicePort.plan_delete_ir lines=(ir_name,)

        await pilot.press("y")
        await pilot.pause()
        assert ("delete_ir", ("V30 Cab",)) in port.calls


async def test_d_then_n_cancels_without_deleting():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        device_table.focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)

        await pilot.press("n")
        await pilot.pause()
        assert port.calls == []
        assert not isinstance(app.screen, ConfirmModal)


async def test_capital_p_renders_plan_lines_verbatim():
    class _PruneDevicePort(FakeDevicePort):
        def plan_prune_irs(self) -> MutationPlan:
            self._check_fail()
            return MutationPlan(
                title="Prune unreferenced device IRs",
                lines=("orphan-1.wav", "orphan-2.wav"),
            )

    port = _PruneDevicePort(state=_CONNECTED, device_irs=list(_DEVICE_IRS))
    core = FakeCore(local_irs=list(_LOCAL_IRS), device=port)
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("P")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        modal_text = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "orphan-1.wav" in modal_text
        assert "orphan-2.wav" in modal_text

        await pilot.press("y")
        await pilot.pause()
        assert ("prune_irs", ()) in port.calls


async def test_capital_p_offline_refuses_without_modal():
    port = FakeDevicePort()  # default offline
    core = FakeCore(local_irs=list(_LOCAL_IRS), device=port)
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("P")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmModal)
        assert port.calls == []
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.last_action.lower()


async def test_capital_r_renames_device_ir_via_inline_input():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        device_table.focus()
        await pilot.pause()
        await pilot.press("R")  # cursor row 0 = V30 Cab
        await pilot.pause()
        rename_input = app.screen.query_one("#irs-rename-input", Input)
        assert rename_input.display is True
        assert rename_input.has_focus
        assert rename_input.value == "V30 Cab"

        rename_input.value = "Renamed"
        await pilot.press("enter")
        await pilot.pause()
        assert ("rename_ir", ("V30 Cab", "Renamed")) in port.calls
        assert rename_input.display is False


async def test_capital_r_escape_cancels_without_renaming():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        device_table.focus()
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()
        rename_input = app.screen.query_one("#irs-rename-input", Input)
        assert rename_input.display is True

        await pilot.press("escape")
        await pilot.pause()
        assert rename_input.display is False
        assert port.calls == []


async def test_capital_r_offline_refuses_without_showing_input():
    port = FakeDevicePort()  # default offline
    core = FakeCore(local_irs=list(_LOCAL_IRS), device=port)
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()
        rename_input = app.screen.query_one("#irs-rename-input", Input)
        assert rename_input.display is False
        assert port.calls == []
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.last_action.lower()


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


async def test_push_under_real_thread_spawn_refreshes_device_pane_without_crashing():
    """The full push-mutation path must marshal both the footer report and the
    device-pane refresh back to the UI thread: under the REAL Textual
    thread-worker spawn, DeviceService.run's (and query's) done callbacks run
    off-thread, so touching widgets or making a second device call directly
    from there would corrupt Textual's UI state instead of just failing a
    synchronous-spawn test."""
    port = FakeDevicePort(state=_CONNECTED, device_irs=list(_DEVICE_IRS))
    core = FakeCore(local_irs=list(_LOCAL_IRS), device=port)
    app = HelixgenTuiApp(core)  # default (real Textual thread-worker) spawn
    async with app.run_test() as pilot:
        await pilot.press("3")
        await _wait_until(
            pilot,
            lambda: app.device_service is not None
            and app.device_service.state.status == "connected",
        )

        device_table = app.screen.query_one("#irs-device-table", DataTable)
        await _wait_until(pilot, lambda: device_table.display is True)
        assert device_table.row_count == 1

        local_table = app.screen.query_one("#irs-local-table", DataTable)
        local_table.focus()
        await pilot.pause()
        await pilot.press("p")  # cursor row 0 = V30 Cab
        await _wait_until(pilot, lambda: ("push_ir", ("deadbeefcafef00d",)) in port.calls)
        await _wait_until(pilot, lambda: app.last_action == "push_ir ok")

        footer = app.screen.query_one(StatusFooter)
        assert "push_ir ok" in footer.last_action
        # The post-mutation refresh round-tripped through
        # RefreshDeviceIrsRequested -> DeviceService.query -> DeviceIrsQueryReady
        # without crashing, leaving the (still-connected) device pane intact.
        assert device_table.display is True
        assert device_table.row_count == 1


# --- Fix 4: r refresh binding + refresh on screen-resume --------------------


async def test_r_refreshes_local_irs():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        assert local_table.row_count == 2
        app.core.local_irs.append(
            IrVM(name="New Local IR", pack=None, irhash="abcd1234abcd1234", on_device=None)
        )
        local_table.focus()
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert local_table.row_count == 3


async def test_screen_resume_refreshes_local_pane():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        assert local_table.row_count == 2
        await pilot.press("1")  # away to library
        await pilot.pause()
        app.core.local_irs.append(
            IrVM(name="New Local IR", pack=None, irhash="abcd1234abcd1234", on_device=None)
        )
        await pilot.press("3")  # back — on_screen_resume re-reads
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        assert local_table.row_count == 3


async def test_screen_resume_refreshes_device_pane():
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        assert device_table.row_count == 1
        await pilot.press("1")  # away to library
        await pilot.pause()
        port.device_irs.append(
            IrVM(name="Greenback", pack=None, irhash="0123456789abcdef", on_device=True)
        )
        await pilot.press("3")  # back — on_screen_resume re-queries the device pane
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        assert device_table.row_count == 2


async def test_local_ir_selection_survives_screen_resume():
    """#8a: the local-pane cursor must survive the on_screen_resume rebuild —
    without capture-then-restore it would snap back to row 0."""
    app, port = _app()
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        assert local_table.row_count == 2
        await pilot.press("down")  # row 1 = Greenback
        assert local_table.cursor_row == 1
        await pilot.press("1")  # away to library
        await pilot.pause()
        await pilot.press("3")  # back — on_screen_resume rebuilds the local pane
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        assert local_table.cursor_row == 1


async def test_device_ir_selection_survives_screen_resume():
    """#8a: the device-pane cursor must survive the on_screen_resume re-query —
    _apply_device_irs rebuilds the table, so it captures/restores too."""
    app, port = _app(
        device_irs=[
            IrVM(name="V30 Cab", pack=None, irhash="deadbeefcafef00d", on_device=True),
            IrVM(name="Greenback", pack=None, irhash="0123456789abcdef", on_device=True),
        ]
    )
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        assert device_table.row_count == 2
        device_table.focus()
        await pilot.press("down")  # row 1 = Greenback
        assert device_table.cursor_row == 1
        await pilot.press("1")  # away to library
        await pilot.pause()
        await pilot.press("3")  # back — on_screen_resume re-queries the device pane
        await pilot.pause()
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        assert device_table.cursor_row == 1


async def test_bracketed_ir_names_render_literally_no_crash():
    """Markup regression (#12): local and device IR names/packs carrying
    brackets must render verbatim in the DataTable cells, never crash."""
    local = [IrVM(name="Bad [/] IR", pack="[reverb]", irhash="deadbeefcafef00d", on_device=None)]
    device = [IrVM(name="Dev [x] IR", pack=None, irhash="deadbeefcafef00d", on_device=True)]
    app, port = _app(device_irs=device, local_irs=local)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        local_table = app.screen.query_one("#irs-local-table", DataTable)
        assert str(local_table.get_cell_at((0, 0))) == "Bad [/] IR"
        assert str(local_table.get_cell_at((0, 1))) == "[reverb]"
        device_table = app.screen.query_one("#irs-device-table", DataTable)
        assert str(device_table.get_cell_at((0, 0))) == "Dev [x] IR"

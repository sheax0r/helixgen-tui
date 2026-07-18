"""Pilot tests for SetlistsScreen: membership, ordering, and sync."""

from __future__ import annotations

import re

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import DeviceStateVM, OpResult, SetlistVM, SyncState, ToneVM
from helixgen_tui.screens.setlists import AddToneModal, SetlistsScreen
from helixgen_tui.widgets.confirm_modal import ConfirmModal
from helixgen_tui.widgets.status_footer import StatusFooter
from textual.widgets import DataTable

from fake_core import FakeCore, FakeDevicePort

_TONES = [
    ToneVM(
        name="AC/DC - Back in Black",
        tone_id="tone-1",
        guitar="SG",
        description="Crunchy rhythm",
        sync=SyncState.SYNCED,
        setlists=("Gig 1",),
    ),
    ToneVM(
        name="Foo Fighters - Everlong",
        tone_id="tone-2",
        guitar="LP",
        description="Clean arpeggios",
        sync=SyncState.LOCAL_ONLY,
        setlists=("Gig 1",),
    ),
    ToneVM(
        name="Radiohead - Everything In Its Right Place",
        tone_id="tone-3",
        guitar=None,
        description=None,
        sync=SyncState.UNKNOWN,
        setlists=(),
    ),
]

_SETLISTS = [
    SetlistVM(name="Gig 1", sync_enabled=True, tones=("tone-1", "tone-2")),
    SetlistVM(name="Gig 2", sync_enabled=False, tones=()),
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


def _app(setlists=None, tones=None, device=None) -> HelixgenTuiApp:
    core = FakeCore(
        tones=list(_TONES) if tones is None else tones,
        setlists=list(_SETLISTS) if setlists is None else setlists,
        device=device,
    )
    return HelixgenTuiApp(core, device_spawn=_sync_spawn)


async def _goto_setlists(pilot):
    await pilot.press("2")
    await pilot.pause()


def _table_rows(table: DataTable) -> list[str]:
    return [
        "\t".join(str(table.get_cell_at((row, col))) for col in range(len(table.columns)))
        for row in range(table.row_count)
    ]


async def test_panes_render_setlists_and_tones_in_manifest_order():
    app = _app()
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        assert isinstance(app.screen, SetlistsScreen)
        tables = app.screen.query(DataTable)
        left, right = tables[0], tables[1]

        left_rendered = "\n".join(_table_rows(left))
        assert "Gig 1" in left_rendered
        assert "Gig 2" in left_rendered
        assert "✓" in left_rendered  # Gig 1 sync-enabled
        assert "○" in left_rendered  # Gig 2 not sync-enabled

        # left cursor starts on row 0 = Gig 1 -> right pane shows its tones in order
        right_rendered = _table_rows(right)
        assert right_rendered == ["AC/DC - Back in Black", "Foo Fighters - Everlong"]


async def test_no_slot_addresses_rendered():
    app = _app()
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tables = app.screen.query(DataTable)
        rendered = "\n".join("\n".join(_table_rows(table)) for table in tables)
        assert re.search(r"\b[1-8][A-D]\b", rendered) is None


async def test_j_moves_tone_down_and_rerenders_new_order():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tables = app.screen.query(DataTable)
        left, right = tables[0], tables[1]
        left.focus()
        right.focus()
        await pilot.pause()

        await pilot.press("J")
        await pilot.pause()

        assert ("move_tone", ("Gig 1", "tone-1", 1)) in core.setlists.calls
        assert _table_rows(right) == ["Foo Fighters - Everlong", "AC/DC - Back in Black"]


async def test_k_moves_tone_up():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tables = app.screen.query(DataTable)
        right = tables[1]
        right.focus()
        right.move_cursor(row=1)
        await pilot.pause()

        await pilot.press("K")
        await pilot.pause()

        assert ("move_tone", ("Gig 1", "tone-2", -1)) in core.setlists.calls
        assert _table_rows(right) == ["Foo Fighters - Everlong", "AC/DC - Back in Black"]


async def test_j_on_last_row_is_a_noop_no_port_call_no_change():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tables = app.screen.query(DataTable)
        right = tables[1]
        right.focus()
        right.move_cursor(row=1)  # last row = tone-2, already at the bottom
        await pilot.pause()

        await pilot.press("J")
        await pilot.pause()

        assert core.setlists.calls == []
        assert _table_rows(right) == ["AC/DC - Back in Black", "Foo Fighters - Everlong"]


async def test_k_on_first_row_is_a_noop_no_port_call_no_change():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tables = app.screen.query(DataTable)
        right = tables[1]
        right.focus()  # cursor already on row 0 = tone-1, already at the top
        await pilot.pause()

        await pilot.press("K")
        await pilot.pause()

        assert core.setlists.calls == []
        assert _table_rows(right) == ["AC/DC - Back in Black", "Foo Fighters - Everlong"]


async def test_d_removes_selected_tone():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tables = app.screen.query(DataTable)
        right = tables[1]
        right.focus()
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()

        assert ("remove_tone", ("Gig 1", "tone-1")) in core.setlists.calls
        assert _table_rows(right) == ["Foo Fighters - Everlong"]


async def test_a_opens_add_tone_picker_excluding_current_members():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tables = app.screen.query(DataTable)
        left = tables[0]
        left.focus()
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()

        assert isinstance(app.screen, AddToneModal)
        picker_table = app.screen.query_one(DataTable)
        rendered = _table_rows(picker_table)
        # tone-1 and tone-2 are already in Gig 1; only tone-3 is a candidate
        assert rendered == ["Radiohead - Everything In Its Right Place"]

        await pilot.press("enter")
        await pilot.pause()

        assert ("add_tone", ("Gig 1", "tone-3")) in core.setlists.calls
        assert not isinstance(app.screen, AddToneModal)
        right = app.screen.query(DataTable)[1]
        assert _table_rows(right) == [
            "AC/DC - Back in Black",
            "Foo Fighters - Everlong",
            "Radiohead - Everything In Its Right Place",
        ]


async def test_a_cancel_makes_no_calls():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, AddToneModal)

        await pilot.press("escape")
        await pilot.pause()
        assert core.setlists.calls == []
        assert isinstance(app.screen, SetlistsScreen)


async def test_s_syncs_selected_setlist_when_connected():
    port = FakeDevicePort(state=_CONNECTED)
    app = _app(device=port)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await pilot.press("S")
        await pilot.pause()
        assert ("sync_setlist", ("Gig 1", False)) in port.calls
        footer = app.screen.query_one(StatusFooter)
        assert "sync_setlist ok" in footer.last_action


async def test_s_offline_refuses_with_footer_reason():
    port = FakeDevicePort()  # default offline
    app = _app(device=port)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await pilot.press("S")
        await pilot.pause()
        assert port.calls == []
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.last_action.lower()


async def test_capital_a_shows_plan_lines_and_y_syncs_all():
    class PlanPort(FakeDevicePort):
        def plan_sync_all(self, gc: bool):
            from helixgen_tui.core.models import MutationPlan

            return MutationPlan(
                title="Sync all setlists?",
                lines=("Gig 1 -> 2 tones", "Gig 2 -> 0 tones"),
            )

    port = PlanPort(state=_CONNECTED)
    app = _app(device=port)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await pilot.press("A")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmModal)
        modal_text = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "Gig 1 -> 2 tones" in modal_text
        assert "Gig 2 -> 0 tones" in modal_text

        await pilot.press("y")
        await pilot.pause()
        assert ("sync_all", (False,)) in port.calls


async def test_capital_a_offline_refuses_without_modal():
    port = FakeDevicePort()  # offline
    app = _app(device=port)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await pilot.press("A")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmModal)
        assert port.calls == []
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.last_action.lower()


async def test_failed_sync_opresult_message_surfaces_in_footer():
    class FailPort(FakeDevicePort):
        def sync_setlist(self, name, gc):
            self.calls.append(("sync_setlist", (name, gc)))
            return OpResult(ok=False, message="sync_setlist: locked by another client")

    port = FailPort(state=_CONNECTED)
    app = _app(device=port)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await pilot.press("S")
        await pilot.pause()
        footer = app.screen.query_one(StatusFooter)
        assert "locked by another client" in footer.last_action


async def test_empty_setlists_renders_with_no_rows_and_no_crash():
    app = _app(setlists=[], tones=[])
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tables = app.screen.query(DataTable)
        left, right = tables[0], tables[1]
        assert left.row_count == 0
        assert right.row_count == 0
        # actions on an empty screen must not raise
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, SetlistsScreen)
        await pilot.press("d")
        await pilot.press("J")
        await pilot.press("K")
        await pilot.press("S")
        await pilot.pause()
        assert isinstance(app.screen, SetlistsScreen)


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


async def test_capital_a_under_real_thread_spawn_shows_plan_lines_verbatim():
    """``action_sync_all``'s plan read must marshal the ConfirmModal open back
    to the UI thread: under the REAL Textual thread-worker spawn,
    DeviceService.query's ``done`` callback runs off-thread, so pushing a
    modal directly from there would corrupt Textual's UI state instead of
    just failing a synchronous-spawn test."""

    class PlanPort(FakeDevicePort):
        def plan_sync_all(self, gc: bool):
            from helixgen_tui.core.models import MutationPlan

            return MutationPlan(
                title="Sync all setlists?",
                lines=("Gig 1 -> 2 tones", "Gig 2 -> 0 tones"),
            )

    port = PlanPort(state=_CONNECTED)
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS), device=port)
    app = HelixgenTuiApp(core)  # default (real Textual thread-worker) spawn
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await _wait_until(
            pilot,
            lambda: (
                app.device_service is not None and app.device_service.state.status == "connected"
            ),
        )

        await pilot.press("A")
        await _wait_until(pilot, lambda: isinstance(app.screen, ConfirmModal))

        modal_text = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "Gig 1 -> 2 tones" in modal_text
        assert "Gig 2 -> 0 tones" in modal_text

        await pilot.press("y")
        await _wait_until(pilot, lambda: ("sync_all", (False,)) in port.calls)


# --- Fix 4: r refresh binding + refresh on screen-resume --------------------


async def test_r_refreshes_setlists_from_table():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        left = app.screen.query(DataTable)[0]
        assert left.row_count == 2
        core.setlists.setlists.append(SetlistVM(name="Gig 3", sync_enabled=False, tones=()))
        left.focus()
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert left.row_count == 3


async def test_screen_resume_refreshes_setlists():
    core = FakeCore(tones=list(_TONES), setlists=list(_SETLISTS))
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        left = app.screen.query(DataTable)[0]
        assert left.row_count == 2
        await pilot.press("1")  # away to library
        await pilot.pause()
        core.setlists.setlists.append(SetlistVM(name="Gig 3", sync_enabled=False, tones=()))
        await _goto_setlists(pilot)  # back — on_screen_resume re-reads
        left = app.screen.query(DataTable)[0]
        assert left.row_count == 3

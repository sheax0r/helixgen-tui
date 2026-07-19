"""Pilot tests for SetlistsScreen: membership, ordering, and sync."""

from __future__ import annotations

import re

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import DeviceStateVM, OpResult, SetlistVM, SyncState, ToneVM
from helixgen_tui.screens.setlists import (
    _SETLIST_TABLE_ID,
    _TONES_TABLE_ID,
    AddToneModal,
    SetlistsScreen,
)
from helixgen_tui.widgets.confirm_modal import ConfirmModal
from helixgen_tui.widgets.status_footer import StatusFooter
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input

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


async def test_setlist_selection_survives_screen_resume():
    """#8a: the left setlist cursor must survive the on_screen_resume rebuild —
    without capture-then-restore it would snap back to row 0."""
    app = _app()
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        left = app.screen.query(DataTable)[0]
        assert left.row_count == 2
        await pilot.press("down")  # row 1 = Gig 2
        assert left.cursor_row == 1
        await pilot.press("1")  # away to library
        await pilot.pause()
        await _goto_setlists(pilot)  # back — on_screen_resume rebuilds both panes
        left = app.screen.query(DataTable)[0]
        assert left.cursor_row == 1
        key = left.coordinate_to_cell_key(Coordinate(1, 0)).row_key.value
        assert key == "Gig 2"


async def test_tones_selection_survives_screen_resume():
    """#8a: the right tones-pane cursor must also survive on_screen_resume —
    the same setlist is re-selected, so its captured tone_id is restored."""
    app = _app()
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        right = app.screen.query(DataTable)[1]
        assert right.row_count == 2  # Gig 1: tone-1, tone-2
        right.focus()
        await pilot.press("down")  # row 1 = Foo Fighters (tone-2)
        assert right.cursor_row == 1
        await pilot.press("1")  # away to library
        await pilot.pause()
        await _goto_setlists(pilot)  # back — on_screen_resume rebuilds both panes
        right = app.screen.query(DataTable)[1]
        assert right.cursor_row == 1


async def test_switching_setlist_resets_tones_cursor_even_when_tone_shared():
    """Switching to a different setlist resets the right pane to the top, even
    if the new setlist shares the tone the cursor was on — the same-setlist
    guard keeps #8a preservation from leaking into a genuine setlist switch."""
    setlists = [
        SetlistVM(name="Gig 1", sync_enabled=True, tones=("tone-1", "tone-2")),
        SetlistVM(name="Gig 2", sync_enabled=False, tones=("tone-3", "tone-2")),
    ]
    app = _app(setlists=setlists)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        right = app.screen.query(DataTable)[1]
        right.focus()
        await pilot.press("down")  # Gig 1 tones row 1 = tone-2
        assert right.cursor_row == 1
        left = app.screen.query(DataTable)[0]
        left.focus()
        await pilot.press("down")  # switch to Gig 2 (also contains tone-2, at row 1)
        await pilot.pause()
        right = app.screen.query(DataTable)[1]
        assert _table_rows(right)[0] == "Radiohead - Everything In Its Right Place"
        assert right.cursor_row == 0  # reset to top, not stuck on shared tone-2


# --- #10: fuzzy filter on the setlists left pane ---------------------------

# "Jazz Chorus Mod" is a gappy match for "jcm" and sorts FIRST natively;
# "JCM800 Crunch" is a contiguous match and must outrank it once filtered.
_FUZZY_SETLISTS = [
    SetlistVM(name="Jazz Chorus Mod", sync_enabled=True, tones=("tone-1",)),
    SetlistVM(name="JCM800 Crunch", sync_enabled=False, tones=("tone-2",)),
    SetlistVM(name="Reverb Night", sync_enabled=False, tones=("tone-3",)),
]


async def _type_setlist_filter(pilot, query: str):
    """Focus the left pane, open the filter with ``/``, type ``query``."""
    pilot.app.screen.query_one(f"#{_SETLIST_TABLE_ID}", DataTable).focus()
    await pilot.pause()
    await pilot.press("slash")
    await pilot.pause()
    for char in query:
        await pilot.press(char)
    await pilot.pause()


async def test_setlist_filter_narrows_and_ranks():
    """Typing into the setlists filter narrows the left pane and puts the best
    match at row 0."""
    app = _app(setlists=list(_FUZZY_SETLISTS))
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await _type_setlist_filter(pilot, "jcm")

        left = app.screen.query_one(f"#{_SETLIST_TABLE_ID}", DataTable)
        names = [row.split("\t")[0] for row in _table_rows(left)]
        assert names == ["JCM800 Crunch", "Jazz Chorus Mod"]  # "Reverb Night" filtered out


async def test_setlist_filter_empty_restores_all():
    """Clearing the filter shows every setlist in native order."""
    app = _app(setlists=list(_FUZZY_SETLISTS))
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await _type_setlist_filter(pilot, "jcm")
        left = app.screen.query_one(f"#{_SETLIST_TABLE_ID}", DataTable)
        assert left.row_count == 2

        await pilot.press("backspace", "backspace", "backspace")
        await pilot.pause()

        names = [row.split("\t")[0] for row in _table_rows(left)]
        assert names == ["Jazz Chorus Mod", "JCM800 Crunch", "Reverb Night"]


async def test_enter_on_setlist_filter_moves_cursor_to_top_hit():
    """Enter acts on the top hit; the right-hand tones pane rebuilds for that
    setlist (RowHighlighted fires as usual). Filtering already parked the cursor
    on the top hit — Enter must never act on a row other than the highlighted
    one, so this asserts the two agree rather than that Enter moves anything."""
    app = _app(setlists=list(_FUZZY_SETLISTS))
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await _type_setlist_filter(pilot, "jcm")

        left = app.screen.query_one(f"#{_SETLIST_TABLE_ID}", DataTable)
        # filtering re-ranked "JCM800 Crunch" to the top and took the cursor
        # with it, off the previously-cursored "Jazz Chorus Mod" (now row 1)
        assert left.cursor_row == 0
        assert app.screen._selected_setlist().name == "JCM800 Crunch"

        await pilot.press("enter")
        await pilot.pause()

        assert left.cursor_row == 0
        assert app.screen._selected_setlist().name == "JCM800 Crunch"
        right = app.screen.query_one(f"#{_TONES_TABLE_ID}", DataTable)
        assert _table_rows(right) == ["Foo Fighters - Everlong"]  # tone-2


async def test_enter_on_setlist_filter_does_not_sync():
    """Enter is navigation only — it must never touch the device."""
    port = FakeDevicePort(state=_CONNECTED)
    core = FakeCore(tones=list(_TONES), setlists=list(_FUZZY_SETLISTS), device=port)
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await _type_setlist_filter(pilot, "jcm")
        await pilot.press("enter")
        await pilot.pause()

        assert port.calls == []
        assert core.setlists.calls == []


async def test_setlist_filter_does_not_break_tones_pane():
    """With a filter active, the tones pane still shows the tones of the
    cursored setlist, not of a stale index."""
    app = _app(setlists=list(_FUZZY_SETLISTS))
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        # "reverb" is the last setlist natively; filtering to it alone must
        # resolve row 0 to Reverb Night, not to native index 0.
        await _type_setlist_filter(pilot, "reverb")

        left = app.screen.query_one(f"#{_SETLIST_TABLE_ID}", DataTable)
        assert left.row_count == 1
        assert app.screen._selected_setlist().name == "Reverb Night"
        right = app.screen.query_one(f"#{_TONES_TABLE_ID}", DataTable)
        assert _table_rows(right) == ["Radiohead - Everything In Its Right Place"]  # tone-3


async def test_setlist_filter_escape_clears_and_refocuses_table():
    """Escape clears a non-empty filter and returns focus to the left pane."""
    app = _app(setlists=list(_FUZZY_SETLISTS))
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await _type_setlist_filter(pilot, "jcm")
        left = app.screen.query_one(f"#{_SETLIST_TABLE_ID}", DataTable)
        assert left.row_count == 2

        await pilot.press("escape")
        await pilot.pause()

        assert app.screen.query_one("#setlists-filter", Input).value == ""
        assert left.row_count == 3
        assert left.has_focus


# --- #10: fuzzy filter + enter-to-add in AddToneModal ----------------------

# Same ranking shape as the setlists fixture: the gappy "jcm" match sorts first
# natively, the contiguous one must outrank it once filtered.
_FUZZY_TONES = [
    ToneVM(
        name="Jazz Chorus Mod",
        tone_id="tone-jazz",
        guitar=None,
        description=None,
        sync=SyncState.LOCAL_ONLY,
        setlists=(),
    ),
    ToneVM(
        name="JCM800 Crunch",
        tone_id="tone-jcm",
        guitar=None,
        description=None,
        sync=SyncState.LOCAL_ONLY,
        setlists=(),
    ),
    ToneVM(
        name="Reverb Night",
        tone_id="tone-reverb",
        guitar=None,
        description=None,
        sync=SyncState.LOCAL_ONLY,
        setlists=(),
    ),
]

# Empty setlist, so every tone above is a candidate in the picker.
_EMPTY_SETLIST = [SetlistVM(name="Gig 1", sync_enabled=True, tones=())]


async def _open_add_tone_modal(pilot, core):
    await _goto_setlists(pilot)
    pilot.app.screen.query_one(f"#{_SETLIST_TABLE_ID}", DataTable).focus()
    await pilot.pause()
    await pilot.press("a")
    await pilot.pause()
    assert isinstance(pilot.app.screen, AddToneModal)


def _fuzzy_picker_app():
    core = FakeCore(tones=list(_FUZZY_TONES), setlists=list(_EMPTY_SETLIST))
    return core, HelixgenTuiApp(core, device_spawn=_sync_spawn)


async def test_add_tone_modal_filter_is_focused_on_mount():
    """The filter input has focus when the modal opens, so the user can type
    immediately."""
    core, app = _fuzzy_picker_app()
    async with app.run_test() as pilot:
        await _open_add_tone_modal(pilot, core)
        assert app.screen.query_one("#add-tone-filter", Input).has_focus


async def test_add_tone_modal_filter_narrows_and_ranks():
    """Typing in the modal filter narrows the candidate list, best match first."""
    core, app = _fuzzy_picker_app()
    async with app.run_test() as pilot:
        await _open_add_tone_modal(pilot, core)
        for char in "jcm":
            await pilot.press(char)
        await pilot.pause()

        picker = app.screen.query_one(DataTable)
        assert _table_rows(picker) == ["JCM800 Crunch", "Jazz Chorus Mod"]


async def test_add_tone_modal_enter_adds_top_hit():
    """Type a query, press Enter in the filter: the modal dismisses with the
    top-ranked tone's id and that tone is added to the setlist."""
    core, app = _fuzzy_picker_app()
    async with app.run_test() as pilot:
        await _open_add_tone_modal(pilot, core)
        for char in "jcm":
            await pilot.press(char)
        await pilot.pause()

        # The pre-filter cursor row ("Jazz Chorus Mod") still matches but ranks
        # second — the cursor must follow the ranking, or the picker highlights
        # one tone and adds another.
        assert app.screen.query_one(DataTable).cursor_row == 0

        await pilot.press("enter")
        await pilot.pause()

        assert not isinstance(app.screen, AddToneModal)
        assert ("add_tone", ("Gig 1", "tone-jcm")) in core.setlists.calls
        right = app.screen.query_one(f"#{_TONES_TABLE_ID}", DataTable)
        assert _table_rows(right) == ["JCM800 Crunch"]


async def test_add_tone_modal_row_selected_still_works():
    """Arrow to a specific row and press Enter on the table: still dismisses
    with THAT row's tone id, not the top hit."""
    core, app = _fuzzy_picker_app()
    async with app.run_test() as pilot:
        await _open_add_tone_modal(pilot, core)
        for char in "jcm":
            await pilot.press(char)
        await pilot.pause()

        picker = app.screen.query_one(DataTable)
        picker.focus()
        await pilot.pause()
        await pilot.press("down")  # row 1 = "Jazz Chorus Mod", not the top hit
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert not isinstance(app.screen, AddToneModal)
        assert ("add_tone", ("Gig 1", "tone-jazz")) in core.setlists.calls


async def test_add_tone_modal_escape_clears_filter_then_cancels():
    """Escape clears a non-empty filter; a second escape cancels with None."""
    core, app = _fuzzy_picker_app()
    async with app.run_test() as pilot:
        await _open_add_tone_modal(pilot, core)
        for char in "jcm":
            await pilot.press(char)
        await pilot.pause()
        picker = app.screen.query_one(DataTable)
        assert picker.row_count == 2

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, AddToneModal)  # still open
        assert app.screen.query_one("#add-tone-filter", Input).value == ""
        assert app.screen.query_one(DataTable).row_count == 3

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SetlistsScreen)
        assert core.setlists.calls == []


async def test_add_tone_modal_escape_still_cancels():
    """Escape on an empty filter dismisses with None; adding nothing."""
    core, app = _fuzzy_picker_app()
    async with app.run_test() as pilot:
        await _open_add_tone_modal(pilot, core)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SetlistsScreen)
        assert core.setlists.calls == []


async def test_bracketed_names_render_literally_no_crash():
    """Markup regression (#12): setlist names, setlist-tone names, and the
    AddToneModal picker must render bracket-bearing names verbatim, never crash."""
    tones = [
        ToneVM(
            name="Bad [/] tone",
            tone_id="tone-b1",
            guitar=None,
            description=None,
            sync=SyncState.SYNCED,
            setlists=("[reverb] set",),
        ),
        ToneVM(
            name="Picker [x] tone",
            tone_id="tone-b2",
            guitar=None,
            description=None,
            sync=SyncState.LOCAL_ONLY,
            setlists=(),
        ),
    ]
    setlists = [SetlistVM(name="[reverb] set", sync_enabled=True, tones=("tone-b1",))]
    core = FakeCore(tones=tones, setlists=setlists)
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        assert isinstance(app.screen, SetlistsScreen)
        left, right = app.screen.query(DataTable)[0], app.screen.query(DataTable)[1]
        assert str(left.get_cell_at((0, 0))) == "[reverb] set"
        assert str(right.get_cell_at((0, 0))) == "Bad [/] tone"

        # AddToneModal picker: the only candidate (tone-b2) shows its brackets literally
        left.focus()
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, AddToneModal)
        picker = app.screen.query_one(DataTable)
        assert str(picker.get_cell_at((0, 0))) == "Picker [x] tone"


async def test_add_tone_modal_enter_on_empty_filter_uses_the_cursor_row():
    """With no query there is no "top hit" — row 0 is just native order — so
    Enter must follow the table cursor rather than committing an arbitrary tone."""
    core, app = _fuzzy_picker_app()
    async with app.run_test() as pilot:
        await _open_add_tone_modal(pilot, core)
        picker = app.screen.query_one(DataTable)
        expected = str(picker.get_cell_at((1, 0)))
        picker.move_cursor(row=1)
        await pilot.pause()

        app.screen.query_one("#add-tone-filter", Input).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        added = [call for call in core.setlists.calls if call[0] == "add_tone"]
        assert len(added) == 1
        tone_id = added[0][1][1]
        assert next(t.name for t in _FUZZY_TONES if t.tone_id == tone_id) == expected


async def test_add_tone_modal_enter_on_no_match_does_not_add():
    core, app = _fuzzy_picker_app()
    async with app.run_test() as pilot:
        await _open_add_tone_modal(pilot, core)
        for char in "zzzz":
            await pilot.press(char)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert core.setlists.calls == []
        assert app.screen.query_one("#add-tone-filter", Input) is not None  # still open


async def test_escape_with_no_filter_leaves_the_tones_pane_focused():
    """Escape unwinds a live query. With nothing to unwind it must not yank the
    cursor off the tones pane mid-reorder."""
    app = _app()
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        tones_table = app.screen.query_one("#setlist-tones-table", DataTable)
        tones_table.focus()
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        assert tones_table.has_focus


async def test_escape_with_a_live_filter_still_returns_to_the_setlists_pane():
    app = _app()
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        filter_input = app.screen.query_one("#setlists-filter", Input)
        filter_input.value = "gig 2"
        await pilot.pause()
        app.screen.query_one("#setlist-tones-table", DataTable).focus()
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        assert filter_input.value == ""
        assert app.screen.query_one("#setlists-table", DataTable).has_focus


async def test_enter_on_an_empty_setlists_filter_does_not_sync():
    app = _app()
    async with app.run_test() as pilot:
        await _goto_setlists(pilot)
        await pilot.press("slash")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.core.setlists.calls == []

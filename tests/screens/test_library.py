"""Pilot tests for LibraryScreen: table rows, detail modal, filter, refresh."""

from __future__ import annotations

import re

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import SetlistVM, SyncState, ToneVM
from helixgen_tui.screens.library import LibraryScreen
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input

from fake_core import FakeCore

_TONES = [
    ToneVM(
        name="AC/DC - Back in Black",
        tone_id="tone-1",
        guitar="SG",
        description="Crunchy rhythm",
        sync=SyncState.SYNCED,
        setlists=("Gig 1", "Gig 2"),
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


def _core(tones=None) -> FakeCore:
    return FakeCore(
        tones=list(_TONES) if tones is None else tones,
        setlists=[SetlistVM(name="Gig 1", sync_enabled=True, tones=())],
    )


async def test_rows_show_names_and_sync_glyphs():
    app = HelixgenTuiApp(_core())
    async with app.run_test():
        table = app.screen.query_one(DataTable)
        assert table.row_count == 3
        rendered = "\n".join(
            str(table.get_cell_at((row, col)))
            for row in range(table.row_count)
            for col in range(len(table.columns))
        )
        assert "AC/DC - Back in Black" in rendered
        assert "Foo Fighters - Everlong" in rendered
        assert "Radiohead - Everything In Its Right Place" in rendered
        assert "✓" in rendered  # synced
        assert "○" in rendered  # local-only
        assert "?" in rendered  # unknown


async def test_no_slot_addresses_rendered():
    app = HelixgenTuiApp(_core())
    async with app.run_test():
        table = app.screen.query_one(DataTable)
        rendered = "\n".join(
            str(table.get_cell_at((row, col)))
            for row in range(table.row_count)
            for col in range(len(table.columns))
        )
        assert re.search(r"\b[1-8][A-D]\b", rendered) is None


def _chain(tone_id="tone-1"):
    from helixgen_tui.core.models import BlockVM, ChainVM, ParamVM, PathVM

    return ChainVM(
        tone_id=tone_id,
        name="AC/DC - Back in Black",
        guitar="SG",
        description="Crunchy rhythm",
        setlists=("Gig 1", "Gig 2"),
        paths=(
            PathVM(
                path=0,
                blocks=(
                    BlockVM(
                        model="HD2_DrvScream808",
                        display="Scream 808",
                        position=1,
                        path=0,
                        enabled=True,
                        params=(ParamVM(name="Drive", value=0.1, type="float", default=0.5),),
                    ),
                ),
            ),
        ),
    )


async def test_enter_opens_tone_editor_with_metadata():
    from helixgen_tui.screens.tone_editor import ToneEditorScreen

    core = FakeCore(
        tones=list(_TONES),
        setlists=[SetlistVM(name="Gig 1", sync_enabled=True, tones=())],
        chains={"tone-1": _chain()},
    )
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # cursor on row 0 = AC/DC (tone-1)
        assert isinstance(app.screen, ToneEditorScreen)
        from textual.widgets import Static

        header = str(app.screen.query_one("#editor-header", Static).render())
        # metadata folded into the editor header (nothing lost from the old modal)
        assert "AC/DC - Back in Black" in header
        assert "Gig 1" in header and "Gig 2" in header


async def test_enter_on_tone_without_chain_stays_on_library():
    """A tone with no editable .hsp (get_chain -> None) must not open the editor;
    the Library screen reports it and stays put."""
    app = HelixgenTuiApp(_core())  # FakeCore has no chains configured
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, LibraryScreen)
        assert "no editable chain" in app.last_action.lower()


async def test_filter_narrows_rows_by_substring():
    app = HelixgenTuiApp(_core())
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        assert table.row_count == 3
        await pilot.press("/")
        filter_input = app.screen.query_one(Input)
        assert filter_input.has_focus
        for char in "everlong":
            await pilot.press(char)
        assert table.row_count == 1
        assert "Foo Fighters - Everlong" in str(table.get_cell_at((0, 0)))


async def test_filter_matches_gappy_subsequence():
    """A gappy query narrows to the intended tone via ordered subsequence match,
    which a contiguous-substring filter would miss. 'ffever' is not a substring
    of 'Foo Fighters - Everlong' but is an ordered subsequence of it."""
    app = HelixgenTuiApp(_core())
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        assert table.row_count == 3
        await pilot.press("/")
        for char in "ffever":
            await pilot.press(char)
        assert table.row_count == 1
        assert "Foo Fighters - Everlong" in str(table.get_cell_at((0, 0)))


_RANKING_TONES = [
    # native order puts the gappy match first — ranking must reorder it below
    # the contiguous one when "jcm" is typed.
    ToneVM(
        name="Jazz Chorus Mod",
        tone_id="tone-jazz",
        guitar="Strat",
        description=None,
        sync=SyncState.SYNCED,
        setlists=(),
    ),
    ToneVM(
        name="JCM800 Crunch",
        tone_id="tone-jcm",
        guitar="LP",
        description=None,
        sync=SyncState.SYNCED,
        setlists=(),
    ),
]


async def test_filter_ranks_best_match_first():
    """With a query active, the best match is row 0 even if it is later in
    native library order."""
    app = HelixgenTuiApp(_core(tones=list(_RANKING_TONES)))
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        assert str(table.get_cell_at((0, 0))) == "Jazz Chorus Mod"
        await pilot.press("/")
        for char in "jcm":
            await pilot.press(char)
        assert table.row_count == 2
        assert str(table.get_cell_at((0, 0))) == "JCM800 Crunch"


async def test_empty_filter_restores_native_order():
    """Clearing the filter restores the library's own ordering, unsorted."""
    app = HelixgenTuiApp(_core(tones=list(_RANKING_TONES)))
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        await pilot.press("/")
        for char in "jcm":
            await pilot.press(char)
        assert str(table.get_cell_at((0, 0))) == "JCM800 Crunch"
        for _ in range(3):
            await pilot.press("backspace")
        assert [str(table.get_cell_at((row, 0))) for row in range(table.row_count)] == [
            "Jazz Chorus Mod",
            "JCM800 Crunch",
        ]


async def test_filter_highlights_matched_characters():
    """The Tone cell for a filtered row is a rich Text whose matched character
    positions carry the highlight style."""
    from helixgen_tui.fuzzy import match
    from helixgen_tui.screens.filterable import HIGHLIGHT_STYLE

    app = HelixgenTuiApp(_core(tones=list(_RANKING_TONES)))
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        await pilot.press("/")
        for char in "jcm":
            await pilot.press(char)
        label = table.get_cell_at((0, 0))
        assert str(label) == "JCM800 Crunch"
        highlighted = {
            offset
            for span in label.spans
            if span.style == HIGHLIGHT_STYLE
            for offset in range(span.start, span.end)
        }
        expected = match("jcm", "JCM800 Crunch")
        assert expected is not None
        assert highlighted == set(expected.indices)


async def test_enter_on_filter_moves_cursor_to_top_hit_without_activating():
    """Enter in the filter input moves the table cursor to the top hit and does
    NOT call the device service (no activate, no sync)."""
    port = FakeDevicePort(state=_CONNECTED)
    core = FakeCore(
        tones=list(_RANKING_TONES),
        setlists=[SetlistVM(name="Gig 1", sync_enabled=True, tones=())],
        device=port,
    )
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        await pilot.press("/")
        for char in "jcm":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause()
        assert table.cursor_row == 0
        assert str(table.get_cell_at((table.cursor_row, 0))) == "JCM800 Crunch"
        assert port.calls == []
        assert isinstance(app.screen, LibraryScreen)


async def test_escape_clears_filter():
    app = HelixgenTuiApp(_core())
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        await pilot.press("/")
        for char in "everlong":
            await pilot.press(char)
        assert table.row_count == 1
        await pilot.press("escape")
        filter_input = app.screen.query_one(Input)
        assert filter_input.value == ""
        assert table.row_count == 3


async def test_refresh_picks_up_newly_appended_tone():
    core = _core()
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        assert table.row_count == 3
        core.library.tones.append(
            ToneVM(
                name="New Tone",
                tone_id="tone-4",
                guitar="Strat",
                description=None,
                sync=SyncState.SYNCED,
                setlists=(),
            )
        )
        assert table.row_count == 3
        await pilot.press("r")
        assert table.row_count == 4


async def test_empty_library_renders_with_no_rows_and_no_crash():
    app = HelixgenTuiApp(FakeCore())
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        assert table.row_count == 0
        # refresh and enter on an empty table must not raise or open a modal.
        await pilot.press("r")
        assert table.row_count == 0
        await pilot.press("enter")
        assert isinstance(app.screen, LibraryScreen)


async def test_filter_with_no_matches_shows_zero_rows_and_enter_is_safe():
    app = HelixgenTuiApp(_core())
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        await pilot.press("/")
        for char in "zzz-no-such-tone":
            await pilot.press(char)
        assert table.row_count == 0

        # move focus back to the (empty) table and confirm enter is a no-op:
        # DataTable.select_cursor guards on an empty table, so no RowSelected
        # is posted and no modal opens.
        table.focus()
        await pilot.pause()
        await pilot.press("enter")
        assert isinstance(app.screen, LibraryScreen)


async def test_refresh_while_filtered_keeps_filter_applied():
    core = _core()
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        await pilot.press("/")
        for char in "everlong":
            await pilot.press(char)
        assert table.row_count == 1

        core.library.tones.append(
            ToneVM(
                name="New Everlong Cover",
                tone_id="tone-5",
                guitar="Tele",
                description=None,
                sync=SyncState.SYNCED,
                setlists=(),
            )
        )
        core.library.tones.append(
            ToneVM(
                name="Unrelated Song",
                tone_id="tone-6",
                guitar=None,
                description=None,
                sync=SyncState.SYNCED,
                setlists=(),
            )
        )

        # refresh from the table (not the filter Input, which would swallow
        # the "r" keystroke as text) — the filter should stay applied to the
        # freshly re-read tone list.
        table.focus()
        await pilot.pause()
        await pilot.press("r")

        assert table.row_count == 2
        rendered_names = {str(table.get_cell_at((row, 0))) for row in range(table.row_count)}
        assert rendered_names == {"Foo Fighters - Everlong", "New Everlong Cover"}


# --- device actions: make-active / sync-tone (Task 5) ----------------------

from helixgen_tui.core.models import DeviceStateVM  # noqa: E402
from helixgen_tui.widgets.confirm_modal import ConfirmModal  # noqa: E402
from helixgen_tui.widgets.status_footer import StatusFooter  # noqa: E402

from fake_core import FakeDevicePort  # noqa: E402

_CONNECTED = DeviceStateVM(
    status="connected",
    model="Helix Stadium",
    address="192.168.4.2",
    active_tone=None,
    detail="",
)


def _sync_spawn(fn):
    fn()


def _device_app(port):
    core = FakeCore(
        tones=list(_TONES),
        setlists=[SetlistVM(name="Gig 1", sync_enabled=True, tones=())],
        device=port,
    )
    return HelixgenTuiApp(core, device_spawn=_sync_spawn)


async def test_footer_shows_connected_model_when_probe_succeeds():
    app = _device_app(FakeDevicePort(state=_CONNECTED))
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.screen.query_one(StatusFooter)
        assert "connected" in footer.device_text
        assert "Helix Stadium" in footer.device_text


async def test_make_active_synced_calls_port_and_footer_shows_result():
    port = FakeDevicePort(state=_CONNECTED)
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("a")  # cursor on row 0 = AC/DC (SYNCED, tone-1)
        await pilot.pause()
        assert ("make_active", ("tone-1",)) in port.calls
        footer = app.screen.query_one(StatusFooter)
        assert "make_active ok" in footer.last_action


async def test_make_active_offline_refuses_without_touching_port():
    port = FakeDevicePort()  # default offline state
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.pause()
        assert port.calls == []
        assert not isinstance(app.screen, ConfirmModal)
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.last_action.lower()


async def test_make_active_local_only_confirms_then_installs_then_activates():
    port = FakeDevicePort(state=_CONNECTED)
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("down")  # row 1 = Foo Fighters (LOCAL_ONLY, tone-2)
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        modal_text = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "install" in modal_text.lower()

        await pilot.press("y")
        await pilot.pause()
        assert ("sync_tone", ("tone-2",)) in port.calls
        assert ("make_active", ("tone-2",)) in port.calls
        assert port.calls.index(("sync_tone", ("tone-2",))) < port.calls.index(
            ("make_active", ("tone-2",))
        )


async def test_make_active_local_only_cancel_makes_no_calls():
    port = FakeDevicePort(state=_CONNECTED)
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("down")
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)

        await pilot.press("n")
        await pilot.pause()
        assert port.calls == []
        assert not isinstance(app.screen, ConfirmModal)


async def test_s_syncs_selected_tone():
    port = FakeDevicePort(state=_CONNECTED)
    app = _device_app(port)
    async with app.run_test() as pilot:
        await pilot.press("s")  # cursor on row 0 = tone-1
        await pilot.pause()
        assert ("sync_tone", ("tone-1",)) in port.calls


async def _wait_until(pilot, cond, timeout=3.0):
    """Pump the event loop until ``cond()`` holds (or fail after ``timeout``)."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await pilot.pause()
        if cond():
            return
    raise AssertionError("condition not met within timeout")


async def test_chained_install_then_activate_under_real_thread_spawn():
    """The install-then-activate chain must marshal its follow-up back to the UI
    thread: under the REAL thread-worker spawn the sync ``done`` callback runs
    off-thread, so it posts a message instead of calling run_worker directly."""
    port = FakeDevicePort(state=_CONNECTED)
    core = FakeCore(
        tones=list(_TONES),
        setlists=[SetlistVM(name="Gig 1", sync_enabled=True, tones=())],
        device=port,
    )
    app = HelixgenTuiApp(core)  # default (real Textual thread-worker) spawn
    async with app.run_test() as pilot:
        await _wait_until(
            pilot,
            lambda: app.device_service is not None
            and app.device_service.state.status == "connected",
        )
        await pilot.press("down")  # row 1 = Foo Fighters (LOCAL_ONLY, tone-2)
        await pilot.press("a")
        await _wait_until(pilot, lambda: isinstance(app.screen, ConfirmModal))

        await pilot.press("y")
        await _wait_until(pilot, lambda: ("make_active", ("tone-2",)) in port.calls)

        assert ("sync_tone", ("tone-2",)) in port.calls
        assert ("make_active", ("tone-2",)) in port.calls
        assert port.calls.index(("sync_tone", ("tone-2",))) < port.calls.index(
            ("make_active", ("tone-2",))
        )

        await _wait_until(pilot, lambda: app.last_action == "make_active ok")
        footer = app.screen.query_one(StatusFooter)
        assert "make_active ok" in footer.last_action


# --- Fix 4: refresh on screen-resume (singleton mode screens) --------------


async def test_screen_resume_refreshes_library():
    core = _core()
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        assert table.row_count == 3
        await pilot.press("2")  # away to setlists
        await pilot.pause()
        core.library.tones.append(
            ToneVM(
                name="New On Resume",
                tone_id="tone-r",
                guitar=None,
                description=None,
                sync=SyncState.SYNCED,
                setlists=(),
            )
        )
        await pilot.press("1")  # back to library — on_screen_resume re-reads
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        assert table.row_count == 4


async def test_selection_survives_screen_resume():
    """#8a: a non-zero cursor row must survive the on_screen_resume rebuild
    (a modal dismiss fires ScreenResume, which rebuilds the table) — without the
    capture-then-restore it would snap back to row 0."""
    core = _core()
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        await pilot.press("down")  # row 1 = Foo Fighters (tone-2)
        assert table.cursor_row == 1
        selected = table.coordinate_to_cell_key(Coordinate(1, 0)).row_key.value
        await pilot.press("2")  # away to setlists
        await pilot.pause()
        await pilot.press("1")  # back — on_screen_resume rebuilds the table
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        assert table.cursor_row == 1
        restored = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value
        assert restored == selected


async def test_bracketed_tone_name_renders_literally_no_crash():
    """Markup regression (#12): a tone name/guitar carrying brackets must render
    verbatim in the DataTable cells and never raise MarkupError."""
    tones = [
        ToneVM(
            name="Bad [/] name",
            tone_id="tone-b1",
            guitar="[reverb]",
            description=None,
            sync=SyncState.SYNCED,
            setlists=(),
        ),
    ]
    app = HelixgenTuiApp(_core(tones=tones))
    async with app.run_test():
        table = app.screen.query_one(DataTable)
        assert table.row_count == 1
        assert str(table.get_cell_at((0, 0))) == "Bad [/] name"
        assert str(table.get_cell_at((0, 1))) == "[reverb]"


async def test_enter_on_a_no_match_filter_does_not_activate_or_crash():
    """The mixin's empty-_visible guard: Enter in the *filter input* (not the
    table) with nothing matching must be a no-op, not an IndexError."""
    port = FakeDevicePort(state=_CONNECTED)
    core = FakeCore(
        tones=list(_RANKING_TONES),
        setlists=[SetlistVM(name="Gig 1", sync_enabled=True, tones=())],
        device=port,
    )
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        table = app.screen.query_one(DataTable)
        await pilot.press("/")
        for char in "zzzz":
            await pilot.press(char)
        await pilot.pause()
        assert table.row_count == 0

        await pilot.press("enter")
        await pilot.pause()
        assert port.calls == []
        assert isinstance(app.screen, LibraryScreen)


async def test_enter_on_an_empty_filter_does_not_activate():
    port = FakeDevicePort(state=_CONNECTED)
    core = FakeCore(
        tones=list(_RANKING_TONES),
        setlists=[SetlistVM(name="Gig 1", sync_enabled=True, tones=())],
        device=port,
    )
    app = HelixgenTuiApp(core, device_spawn=_sync_spawn)
    async with app.run_test() as pilot:
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert port.calls == []
        assert isinstance(app.screen, LibraryScreen)

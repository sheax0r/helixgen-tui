"""Pilot tests for ToneEditorScreen: chain/param display, nudge/clamp, manual
entry, dirty indicator, save wiring, and the markup regression. All driven by
FakeCore/FakeEditorPort — no real helixgen, no device.
"""

from __future__ import annotations

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import (
    BlockVM,
    ChainVM,
    ParamVM,
    PathVM,
    SyncState,
    ToneVM,
)
from helixgen_tui.screens.library import LibraryScreen
from helixgen_tui.screens.tone_editor import ToneEditorScreen
from textual.widgets import DataTable, Input, Static

from fake_core import FakeCore, FakeEditorPort


def _chain(tone_id="tone-1"):
    drive = BlockVM(
        model="HD2_DrvScream808",
        display="Scream 808",
        position=1,
        path=0,
        enabled=True,
        params=(
            ParamVM(name="Drive", value=0.10, type="float", default=0.5),
            ParamVM(name="Gate", value=False, type="bool", default=False),
            ParamVM(name="Voicing", value=2, type="int", default=1),
        ),
    )
    amp = BlockVM(
        model="HD2_AmpBrit2204Custom",
        display="Brit 2204",
        position=4,
        path=0,
        enabled=False,
        params=(ParamVM(name="Bass", value=0.50, type="float", default=0.5),),
    )
    return ChainVM(
        tone_id=tone_id,
        name="Test Tone [Live]",
        guitar="SG",
        description="Boost [reverb] then [b]bright[/b]",
        setlists=("Gig 1",),
        paths=(PathVM(path=0, blocks=(drive, amp)),),
    )


_TONES = [
    ToneVM(
        name="Test Tone [Live]",
        tone_id="tone-1",
        guitar="SG",
        description="desc",
        sync=SyncState.SYNCED,
        setlists=("Gig 1",),
    )
]


def _app(chain=None):
    chain = _chain() if chain is None else chain
    core = FakeCore(tones=list(_TONES), chains={chain.tone_id: chain})
    return HelixgenTuiApp(core)


def _params_cells(app):
    table = app.screen.query_one("#editor-params", DataTable)
    return [
        (str(table.get_cell_at((r, 0))), str(table.get_cell_at((r, 1))))
        for r in range(table.row_count)
    ]


def _blocks_cells(app):
    table = app.screen.query_one("#editor-blocks", DataTable)
    return [
        tuple(str(table.get_cell_at((r, c))) for c in range(len(table.columns)))
        for r in range(table.row_count)
    ]


async def test_enter_from_library_opens_editor_with_chain():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, ToneEditorScreen)
        blocks = _blocks_cells(app)
        # both blocks listed, grouped by path, with model + pos + state
        assert any("Scream 808" in row[1] and row[0] == "0" for row in blocks)
        assert any("Brit 2204" in row[1] and "bypass" in row[3] for row in blocks)
        # params of the first-selected block are shown
        pcells = _params_cells(app)
        names = [n for n, _ in pcells]
        assert "Drive" in names and "Gate" in names


async def test_float_nudge_changes_by_step_and_clamps():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")  # open editor
        await pilot.press("tab")  # focus params pane
        # Drive starts at 0.10; right nudges +0.01
        await pilot.press("right")
        pcells = dict(_params_cells(app))
        assert pcells["Drive"] == "0.11"
        # clamp at 1.0: many rights never exceed 1.00
        for _ in range(105):
            await pilot.press("right")
        pcells = dict(_params_cells(app))
        assert pcells["Drive"] == "1.00"
        # clamp at 0.0 going the other way
        for _ in range(105):
            await pilot.press("left")
        pcells = dict(_params_cells(app))
        assert pcells["Drive"] == "0.00"


async def test_bool_toggle_and_int_nudge():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")  # params pane, Drive selected
        await pilot.press("down")  # -> Gate (bool)
        await pilot.press("right")
        assert dict(_params_cells(app))["Gate"] == "on"
        await pilot.press("right")
        assert dict(_params_cells(app))["Gate"] == "off"
        await pilot.press("down")  # -> Voicing (int, starts 2)
        await pilot.press("right")
        assert dict(_params_cells(app))["Voicing"] == "3"
        await pilot.press("left")
        await pilot.press("left")
        assert dict(_params_cells(app))["Voicing"] == "1"


async def test_manual_entry_commits_valid_value():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")
        await pilot.press("enter")  # open manual entry on Drive
        assert isinstance(app.screen.query_one(Input), Input)
        inp = app.screen.query_one("#editor-entry", Input)
        inp.value = "0.42"
        await pilot.press("enter")  # commit
        assert dict(_params_cells(app))["Drive"] == "0.42"


async def test_manual_entry_rejects_bad_input():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")
        await pilot.press("enter")
        inp = app.screen.query_one("#editor-entry", Input)
        inp.value = "not-a-number"
        await pilot.press("enter")
        # rejected: value unchanged, entry stays open, footer shows the error
        assert dict(_params_cells(app))["Drive"] == "0.10"
        assert app.screen.query("#editor-entry")  # still open
        assert "invalid" in app.last_action.lower()


async def test_manual_entry_clamps_out_of_range_float():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")
        await pilot.press("enter")
        inp = app.screen.query_one("#editor-entry", Input)
        inp.value = "5.0"
        await pilot.press("enter")
        assert dict(_params_cells(app))["Drive"] == "1.00"


async def test_dirty_indicator_appears_and_clears_on_save():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        header = app.screen.query_one("#editor-header", Static)
        assert "unsaved" not in str(header.render())
        await pilot.press("tab")
        await pilot.press("right")  # edit Drive
        assert app.screen.is_dirty
        assert "unsaved" in str(app.screen.query_one("#editor-header", Static).render())
        await pilot.press("s")  # save
        assert not app.screen.is_dirty
        assert "unsaved" not in str(app.screen.query_one("#editor-header", Static).render())


async def test_save_calls_adapter_with_changes():
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")
        await pilot.press("right")  # Drive 0.10 -> 0.11
        await pilot.press("s")
        assert len(editor.calls) == 1
        tone_id, changes = editor.calls[0]
        assert tone_id == "tone-1"
        assert len(changes) == 1
        ch = changes[0]
        assert ch.model == "HD2_DrvScream808"
        assert ch.path == 0 and ch.position == 1 and ch.param == "Drive"
        assert abs(ch.value - 0.11) < 1e-9


async def test_edit_back_to_original_is_not_dirty():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")
        await pilot.press("right")  # 0.10 -> 0.11
        assert app.screen.is_dirty
        await pilot.press("left")  # 0.11 -> 0.10 (back to disk value)
        assert not app.screen.is_dirty


async def test_leave_with_unsaved_confirms():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")
        await pilot.press("right")  # dirty
        await pilot.press("escape")  # should raise a confirm, not leave
        from helixgen_tui.widgets.confirm_modal import ConfirmModal

        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("y")  # discard
        assert isinstance(app.screen, LibraryScreen)


async def test_leave_clean_pops_immediately():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, ToneEditorScreen)
        await pilot.press("escape")
        assert isinstance(app.screen, LibraryScreen)


async def test_bracketed_param_and_block_text_render_literally():
    """Markup regression (#12): a value/name carrying brackets must render
    verbatim in DataTable cells and the header, never be stripped or crash."""
    chain = ChainVM(
        tone_id="tone-1",
        name="Test Tone [Live]",
        guitar="SG",
        description="Boost [reverb] then [b]bright[/b]",
        setlists=("Gig 1",),
        paths=(
            PathVM(
                path=0,
                blocks=(
                    BlockVM(
                        model="Weird [/] Model",
                        display="Weird [/] Model",
                        position=1,
                        path=0,
                        enabled=True,
                        params=(ParamVM(name="Odd [x]", value="a[b]c", type="str", default=None),),
                    ),
                ),
            ),
        ),
    )
    app = _app(chain)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, ToneEditorScreen)
        blocks = _blocks_cells(app)
        assert any("Weird [/] Model" in row[1] for row in blocks)
        pcells = _params_cells(app)
        assert ("Odd [x]", "a[b]c") in pcells
        header = str(app.screen.query_one("#editor-header", Static).render())
        assert "[Live]" in header
        assert "[reverb]" in header

"""Pilot tests for ToneEditorScreen: chain/param display, nudge/clamp, manual
entry, dirty indicator, save wiring, and the markup regression. All driven by
FakeCore/FakeEditorPort — no real helixgen, no device.
"""

from __future__ import annotations

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import (
    BlockVM,
    ChainVM,
    OutputVM,
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
        output=OutputVM(level=-3.0, pan=0.5),
        input_source="both",
    )


def _parallel_chain(tone_id="tone-1"):
    top = BlockVM(
        model="TopMod",
        display="Top Block",
        position=1,
        path=0,
        enabled=True,
        params=(ParamVM(name="TopP", value=0.10, type="float", default=0.5),),
    )
    bottom = BlockVM(
        model="BotMod",
        display="Bot Block",
        position=1,
        path=1,
        enabled=True,
        params=(ParamVM(name="BotP", value=0.20, type="float", default=0.5),),
    )
    return ChainVM(
        tone_id=tone_id,
        name="Parallel Tone",
        guitar=None,
        description=None,
        setlists=(),
        paths=(PathVM(path=0, blocks=(top,)), PathVM(path=1, blocks=(bottom,))),
        output=OutputVM(level=0.0, pan=0.5),
        input_source="both",
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


def _chain_text(app):
    return str(app.screen.query_one("#editor-chain", Static).render())


async def test_enter_from_library_opens_editor_with_chain():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, ToneEditorScreen)
        text = _chain_text(app)
        # both blocks rendered horizontally, with the input + output nodes
        assert "Scream 808" in text
        assert "Brit 2204" in text
        assert "byp" in text  # amp is bypassed
        assert "IN:both" in text  # input head node
        assert "OUT" in text  # output terminal node
        # params of the first-selected block are shown
        pcells = _params_cells(app)
        names = [n for n, _ in pcells]
        assert "Drive" in names and "Gate" in names


async def test_chain_renders_horizontally_with_io_nodes():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        text = _chain_text(app)
        # left-to-right order: input, then blocks, then output
        assert text.index("IN:both") < text.index("Scream 808")
        assert text.index("Scream 808") < text.index("Brit 2204")
        assert text.index("Brit 2204") < text.index("OUT")
        # output node carries level + pan
        assert "L-3.0" in text and "P0.50" in text


async def test_chain_navigation_moves_selection_and_updates_params():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        # cursor starts on the first block -> its params in the inspector
        assert "Drive" in [n for n, _ in _params_cells(app)]
        # right -> amp (Brit 2204) -> only its param (Bass)
        await pilot.press("right")
        assert [n for n, _ in _params_cells(app)] == ["Bass"]
        # right -> output node -> inspector shows level/pan read-only
        await pilot.press("right")
        pnames = [n for n, _ in _params_cells(app)]
        assert "Level" in pnames and "Pan" in pnames
        # right again clamps at the output terminal
        await pilot.press("right")
        assert [n for n, _ in _params_cells(app)] == ["Level", "Pan"]
        # walk back left: output -> amp -> drive -> input head node
        await pilot.press("left")
        assert [n for n, _ in _params_cells(app)] == ["Bass"]
        await pilot.press("left")
        assert "Drive" in [n for n, _ in _params_cells(app)]
        await pilot.press("left")
        assert [n for n, _ in _params_cells(app)] == ["Source"]
        # left clamps at the input head node
        await pilot.press("left")
        assert [n for n, _ in _params_cells(app)] == ["Source"]


async def test_multi_lane_render_and_vertical_navigation():
    app = _app(_parallel_chain())
    async with app.run_test() as pilot:
        await pilot.press("enter")
        text = _chain_text(app)
        # both DSP paths are stacked on separate rows
        assert "Top Block" in text and "Bot Block" in text
        assert "\n" in text
        # split/join connectors drawn for a parallel-routed tone
        assert "+" in text
        # cursor starts on lane 0 -> its param
        assert [n for n, _ in _params_cells(app)] == ["TopP"]
        # down moves across lanes to the second path
        await pilot.press("down")
        assert [n for n, _ in _params_cells(app)] == ["BotP"]
        await pilot.press("up")
        assert [n for n, _ in _params_cells(app)] == ["TopP"]


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
        assert "Weird [/] Model" in _chain_text(app)
        pcells = _params_cells(app)
        assert ("Odd [x]", "a[b]c") in pcells
        header = str(app.screen.query_one("#editor-header", Static).render())
        assert "[Live]" in header
        assert "[reverb]" in header


async def test_manual_entry_with_bracket_param_name_does_not_crash():
    """A param whose NAME carries markup brackets must be manually-editable
    without crashing: the entry prompt escapes the name (border_title is
    markup-parsed), and rejecting a bracket-bearing VALUE routes an error
    through the footer (now a rich Text, not markup-parsed)."""
    chain = ChainVM(
        tone_id="tone-1",
        name="T",
        guitar=None,
        description=None,
        setlists=(),
        paths=(
            PathVM(
                path=0,
                blocks=(
                    BlockVM(
                        model="M",
                        display="M",
                        position=1,
                        path=0,
                        enabled=True,
                        params=(ParamVM(name="Gain [/]", value=0.5, type="float", default=0.5),),
                    ),
                ),
            ),
        ),
    )
    app = _app(chain)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")
        await pilot.press("enter")  # open manual entry on the bracket-named param
        assert app.screen.query("#editor-entry")  # opened, did not crash
        inp = app.screen.query_one("#editor-entry", Input)
        inp.value = "[/]"  # a malformed-markup value
        await pilot.press("enter")  # reject -> error to the footer
        # app is still alive and on the editor; footer did not raise MarkupError
        assert isinstance(app.screen, ToneEditorScreen)
        assert "invalid" in app.last_action.lower()
        assert dict(_params_cells(app))["Gain [/]"] == "0.50"


async def test_long_description_does_not_crowd_out_the_tables():
    """A tone with a long multi-paragraph description must not let the header
    eat the viewport: the header stays bounded and the block/param tables keep
    real height. Regression for the header rendering the whole description raw
    (height: auto) and collapsing the tables to ~0."""
    marker = "ZZUNIQUELATERPARAGRAPHMARKERZZ"
    paragraphs = [f"Paragraph {i}: " + "lorem ipsum dolor sit " * 4 for i in range(70)]
    paragraphs[64] += " " + marker  # marker lives in a later paragraph
    long_desc = "\n".join(paragraphs)
    assert len(long_desc) > 2000
    assert long_desc.count("\n") > 60

    import dataclasses

    chain = dataclasses.replace(_chain(), description=long_desc)
    app = _app(chain)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, ToneEditorScreen)

        header = app.screen.query_one("#editor-header", Static)
        params = app.screen.query_one("#editor-params", DataTable)

        # Header is bounded — it must not expand to render the whole description.
        assert header.outer_size.height <= 6

        # The params inspector keeps real height instead of collapsing to ~0.
        assert params.outer_size.height >= 5

        # And the data is actually there.
        assert "Scream 808" in _chain_text(app)
        assert "Drive" in [n for n, _ in _params_cells(app)]

        # The description is compacted to a single line: the later-paragraph
        # marker is dropped and the header carries only its 3 structural lines.
        rendered = str(header.render())
        assert marker not in rendered
        assert rendered.count("\n") <= 3


async def test_add_block_serial_opens_picker_and_records():
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # open editor, first block selected
        await pilot.press("a")  # add block -> picker
        from helixgen_tui.widgets.block_picker_modal import BlockPickerModal

        assert isinstance(app.screen, BlockPickerModal)
        await pilot.press("enter")  # pick first category
        await pilot.press("enter")  # pick first model
        await pilot.pause()
        # an add_block call recorded, after the selected (first) block
        adds = [c for c in editor.calls if c[0] == "add_block"]
        assert len(adds) == 1
        _, (tone_id, after_coords, model) = adds[0]
        assert tone_id == "tone-1"
        assert after_coords == ("HD2_DrvScream808", 0, 1)
        assert model == "DrvA"  # first model of the first catalogue category
        # chain re-read shows the new block (fake uses model id as display)
        assert "DrvA" in _chain_text(app)


async def test_add_block_to_emptied_serial_lane_appends():
    # Removing every block from a serial lane must not be a dead-end: with no
    # block selected, `a` appends at the end (after=None) so the lane refills.
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # open editor, first block selected
        await pilot.press("x")  # remove first block
        await pilot.pause()
        await pilot.press("x")  # remove the remaining block -> lane empty
        await pilot.pause()
        await pilot.press("a")  # add with nothing selected
        from helixgen_tui.widgets.block_picker_modal import BlockPickerModal

        assert isinstance(app.screen, BlockPickerModal)  # not a no-op
        await pilot.press("enter")  # pick first category
        await pilot.press("enter")  # pick first model
        await pilot.pause()
        adds = [c for c in editor.calls if c[0] == "add_block"]
        assert len(adds) == 1
        _, (tone_id, after_coords, model) = adds[0]
        assert tone_id == "tone-1"
        assert after_coords is None  # appended at end, no anchor block
        assert model == "DrvA"
        assert "DrvA" in _chain_text(app)


async def test_add_block_parallel_refuses_and_records_nothing():
    editor = FakeEditorPort(
        chains={"tone-1": _parallel_chain()}, parallel_tones={"tone-1"}
    )
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("a")  # refuse: parallel-routed
        from helixgen_tui.widgets.block_picker_modal import BlockPickerModal

        assert not isinstance(app.screen, BlockPickerModal)  # no picker
        assert [c for c in editor.calls if c[0] == "add_block"] == []
        assert "parallel" in app.last_action.lower()


async def test_remove_block_parallel_refuses_and_records_nothing():
    editor = FakeEditorPort(
        chains={"tone-1": _parallel_chain()}, parallel_tones={"tone-1"}
    )
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("x")  # refuse: parallel-routed
        assert [c for c in editor.calls if c[0] == "remove_block"] == []
        assert "parallel" in app.last_action.lower()


async def test_remove_block_serial_records():
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # first block (Scream 808) selected
        await pilot.press("x")
        await pilot.pause()
        removes = [c for c in editor.calls if c[0] == "remove_block"]
        assert len(removes) == 1
        _, (tone_id, coords) = removes[0]
        assert tone_id == "tone-1"
        assert coords == ("HD2_DrvScream808", 0, 1)
        # gone from the re-read chain
        assert "Scream 808" not in _chain_text(app)


async def test_bypass_records_flipped_enabled():
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # Scream 808 (enabled=True) selected
        await pilot.press("b")
        await pilot.pause()
        byps = [c for c in editor.calls if c[0] == "set_bypass"]
        assert len(byps) == 1
        _, (tone_id, coords, enabled) = byps[0]
        assert tone_id == "tone-1"
        assert coords == ("HD2_DrvScream808", 0, 1)
        assert enabled is False  # was enabled, toggled to bypassed


async def test_bypass_refused_while_dirty_preserves_edit():
    # A structural write persists immediately and reloads the chain, dropping the
    # in-memory param working set. While dirty the verb must refuse, not silently
    # discard the unsaved edit.
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # Scream 808 selected
        await pilot.press("tab")  # params pane
        await pilot.press("right")  # nudge Drive -> dirty
        assert app.screen.is_dirty
        await pilot.press("b")  # bypass refused while dirty
        await pilot.pause()
        assert [c for c in editor.calls if c[0] == "set_bypass"] == []
        assert app.screen.is_dirty  # unsaved edit preserved
        assert "save or discard" in app.last_action.lower()


async def test_add_refused_while_dirty_does_not_open_picker():
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # first block selected
        await pilot.press("tab")  # params pane
        await pilot.press("right")  # nudge Drive -> dirty
        assert app.screen.is_dirty
        await pilot.press("a")  # add refused while dirty
        from helixgen_tui.widgets.block_picker_modal import BlockPickerModal

        assert not isinstance(app.screen, BlockPickerModal)  # picker never opened
        assert [c for c in editor.calls if c[0] == "add_block"] == []
        assert app.screen.is_dirty
        assert "save or discard" in app.last_action.lower()


async def test_swap_model_records():
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # Scream 808 selected
        await pilot.press("w")  # swap -> picker
        from helixgen_tui.widgets.block_picker_modal import BlockPickerModal

        assert isinstance(app.screen, BlockPickerModal)
        await pilot.press("enter")  # category
        await pilot.press("enter")  # model
        await pilot.pause()
        swaps = [c for c in editor.calls if c[0] == "swap_model"]
        assert len(swaps) == 1
        _, (tone_id, coords, model) = swaps[0]
        assert tone_id == "tone-1"
        assert coords == ("HD2_DrvScream808", 0, 1)
        assert model == "DrvA"


async def test_output_edit_records_set_output_and_dirty_then_saves():
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        # walk to the output node: right (amp) -> right (output)
        await pilot.press("right")
        await pilot.press("right")
        assert [n for n, _ in _params_cells(app)] == ["Level", "Pan"]
        await pilot.press("tab")  # focus params pane
        await pilot.press("down")  # select Pan
        await pilot.press("right")  # nudge pan 0.50 -> 0.51
        assert app.screen.is_dirty
        assert dict(_params_cells(app))["Pan"] == "0.51"
        await pilot.press("s")  # save via existing save path
        await pilot.pause()
        outs = [c for c in editor.calls if c[0] == "set_output"]
        assert len(outs) == 1
        _, (tone_id, level, pan) = outs[0]
        assert tone_id == "tone-1"
        assert abs(level - (-3.0)) < 1e-9
        assert abs(pan - 0.51) < 1e-9
        assert not app.screen.is_dirty


async def test_input_node_is_read_only():
    editor = FakeEditorPort(chains={"tone-1": _chain()})
    core = FakeCore(tones=list(_TONES), editor=editor)
    app = HelixgenTuiApp(core)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        # walk left to the input head node
        await pilot.press("left")
        assert [n for n, _ in _params_cells(app)] == ["Source"]
        # no structural/output write is available on the input node
        await pilot.press("a")
        await pilot.press("x")
        await pilot.press("b")
        await pilot.press("w")
        await pilot.press("tab")
        await pilot.press("right")  # would nudge if editable
        assert not app.screen.is_dirty
        # only the read verbs (if any) ran; no structural/output writes
        writes = [
            c
            for c in editor.calls
            if c[0] in ("add_block", "remove_block", "set_bypass", "swap_model", "set_output")
        ]
        assert writes == []


async def test_float_edit_back_to_display_value_clears_dirty_for_non_2dp_disk_value():
    """An on-disk float not aligned to 2dp (0.333 -> shows 0.33) must still
    prune cleanly: nudge up then down lands on 0.33 and dirty clears, so a
    no-op save can't silently rewrite 0.333 -> 0.33."""
    chain = ChainVM(
        tone_id="tone-1",
        name="T",
        guitar=None,
        description=None,
        setlists=(),
        paths=(
            PathVM(
                path=0,
                blocks=(
                    BlockVM(
                        model="M",
                        display="M",
                        position=1,
                        path=0,
                        enabled=True,
                        params=(ParamVM(name="Mix", value=0.333, type="float", default=0.5),),
                    ),
                ),
            ),
        ),
    )
    app = _app(chain)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.press("tab")
        assert not app.screen.is_dirty
        await pilot.press("right")  # 0.33 -> 0.34
        assert app.screen.is_dirty
        await pilot.press("left")  # 0.34 -> 0.33 (== on-disk at display precision)
        assert not app.screen.is_dirty

"""The clickable key-hints footer (Textual's ``Footer``) on every mode screen.

Shipped after a user couldn't discover the setlists screen's ``a``/``d``/…
actions: nothing on screen advertised the keys (the StatusFooter shows device
state, and the ``?`` overlay is itself an invisible binding). The bindings
footer both displays each screen's keys and triggers them on click, so it's
also the app's mouse path to actions.
"""

from __future__ import annotations

from textual.widgets import Footer
from textual.widgets._footer import FooterKey

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import SetlistVM, SyncState, ToneVM

from fake_core import FakeCore

_TONES = [
    ToneVM(
        name="Clean Blackface",
        tone_id="tone-1",
        guitar="Strat",
        description="",
        sync=SyncState.SYNCED,
        setlists=(),
    ),
    ToneVM(
        name="Rhythm Crunch",
        tone_id="tone-2",
        guitar="LP",
        description="",
        sync=SyncState.LOCAL_ONLY,
        setlists=(),
    ),
]


def _footer_descriptions(app: HelixgenTuiApp) -> list[str]:
    return [key.description for key in app.screen.query(FooterKey)]


async def test_every_mode_screen_shows_its_bindings_in_a_footer() -> None:
    app = HelixgenTuiApp(FakeCore())
    expected = {
        "library": "Activate",
        "setlists": "Add tone",
        "irs": "Push",
        "device": "Backup",
    }
    async with app.run_test() as pilot:
        for key, mode in [("1", "library"), ("2", "setlists"), ("3", "irs"), ("4", "device")]:
            await pilot.press(key)
            await pilot.pause()
            assert app.screen.query(Footer), f"no Footer on {mode} screen"
            descriptions = _footer_descriptions(app)
            assert expected[mode] in descriptions, f"{mode}: {descriptions}"
            # Global helpers stay visible; tab keys stay hidden (TabStrip has them).
            assert "Help" in descriptions
            assert "Library" not in descriptions


async def test_filter_binding_is_advertised_on_every_filtered_screen() -> None:
    """The `/` filter shipped on Setlists and IRs (#10) must be discoverable —
    the bindings are declared without `show=False`, so the footer lists them."""
    app = HelixgenTuiApp(FakeCore(tones=_TONES))
    async with app.run_test(size=(140, 40)) as pilot:
        for key, mode in [("1", "library"), ("2", "setlists"), ("3", "irs")]:
            await pilot.press(key)
            await pilot.pause()
            descriptions = _footer_descriptions(app)
            assert "Filter" in descriptions, f"{mode}: {descriptions}"


async def test_clicking_a_footer_key_triggers_the_action() -> None:
    from helixgen_tui.screens.setlists import AddToneModal

    core = FakeCore(tones=_TONES, setlists=[SetlistVM(name="Gig", sync_enabled=True, tones=())])
    app = HelixgenTuiApp(core)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        add_key = next(
            key for key in app.screen.query(FooterKey) if key.description == "Add tone"
        )
        await pilot.click(offset=add_key.region.center)
        await pilot.pause()
        assert isinstance(app.screen, AddToneModal)


async def test_double_click_selects_a_row_like_enter() -> None:
    """First click moves the DataTable cursor, second click on the same row
    posts RowSelected — so double-clicking a library tone opens its editor."""
    from textual.widgets import DataTable

    from helixgen_tui.core.models import BlockVM, ChainVM, ParamVM, PathVM
    from helixgen_tui.screens.tone_editor import ToneEditorScreen

    chain = ChainVM(
        tone_id="tone-2",
        name="Rhythm Crunch",
        guitar="LP",
        description="",
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
                        params=(ParamVM(name="p", value=0.5, type="float", default=0.5),),
                    ),
                ),
            ),
        ),
    )
    app = HelixgenTuiApp(FakeCore(tones=_TONES, chains={"tone-2": chain}))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.screen.query_one("#library-table", DataTable)
        target = table.region.offset + (2, 2)  # inside the second data row
        await pilot.click(offset=target)
        await pilot.click(offset=target)
        await pilot.pause()
        assert isinstance(app.screen, ToneEditorScreen)


async def test_status_and_bindings_footers_do_not_overlap() -> None:
    """Both bars docked to the screen edge individually stack on the same row
    (the bindings footer painted over the device status). They now share one
    docked container: status bar directly above the key bar."""
    from helixgen_tui.widgets.status_footer import StatusFooter

    app = HelixgenTuiApp(FakeCore())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        status = app.screen.query_one(StatusFooter)
        footer = app.screen.query_one(Footer)
        assert status.region.height == 1 and footer.region.height == 1
        assert status.region.y == footer.region.y - 1

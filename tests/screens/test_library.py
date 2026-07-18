"""Pilot tests for LibraryScreen: table rows, detail modal, filter, refresh."""

from __future__ import annotations

import re

from helixgen_tui.app import HelixgenTuiApp
from helixgen_tui.core.models import SetlistVM, SyncState, ToneVM
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


async def test_enter_opens_detail_modal_with_setlists():
    from helixgen_tui.screens.library import ToneDetailModal

    app = HelixgenTuiApp(_core())
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, ToneDetailModal)
        modal_text = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "Gig 1" in modal_text
        assert "Gig 2" in modal_text
        assert "AC/DC - Back in Black" in modal_text


async def test_escape_closes_detail_modal():
    from helixgen_tui.screens.library import ToneDetailModal

    app = HelixgenTuiApp(_core())
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, ToneDetailModal)
        await pilot.press("escape")
        assert not isinstance(app.screen, ToneDetailModal)


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

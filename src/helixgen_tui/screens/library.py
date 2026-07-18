"""LibraryScreen: read-only browse of the tone library — table, detail modal, filter."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from helixgen_tui.core.models import SyncState, ToneVM
from helixgen_tui.screens.base import LibrarianScreen

_SYNC_GLYPH = {
    SyncState.SYNCED: "✓",  # check mark
    SyncState.LOCAL_ONLY: "○",  # white circle
    SyncState.UNKNOWN: "?",
}

_FILTER_ID = "library-filter"
_TABLE_ID = "library-table"


class ToneDetailModal(ModalScreen[None]):
    """Modal showing a single tone's name, guitar, setlists, and description."""

    DEFAULT_CSS = """
    ToneDetailModal {
        align: center middle;
    }

    ToneDetailModal > Container {
        width: auto;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $panel;
    }
    """

    BINDINGS = [Binding("escape", "dismiss_detail", "Close", show=False)]

    def __init__(self, tone: ToneVM) -> None:
        self._tone = tone
        super().__init__()

    def compose(self) -> ComposeResult:
        tone = self._tone
        setlists = ", ".join(tone.setlists) if tone.setlists else "—"
        lines = [
            f"Name: {tone.name}",
            f"Guitar: {tone.guitar or '—'}",
            f"Setlists: {setlists}",
            f"Description: {tone.description or '—'}",
        ]
        with Container():
            yield Static("\n".join(lines))

    def action_dismiss_detail(self) -> None:
        self.dismiss()


class LibraryScreen(LibrarianScreen):
    """Library-mode screen: browse tones, view details, filter, refresh — all read-only."""

    TAB_LABEL = "Library"
    MODE_NAME = "library"

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "focus_filter", "Filter", key_display="/"),
        Binding("escape", "clear_filter", "Clear", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tones: list[ToneVM] = []

    def body(self) -> ComposeResult:
        yield Input(placeholder="filter", id=_FILTER_ID)
        yield DataTable(id=_TABLE_ID, cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one(f"#{_TABLE_ID}", DataTable)
        table.add_columns("Tone", "Guitar", "Sync")
        self.refresh_tones()
        table.focus()

    def refresh_tones(self) -> None:
        """Re-read the tone list from core.library and rebuild the table.

        A plain sync method (not a worker) — local library reads are cheap.
        """
        self._tones = self.app.core.library.list_tones()
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        table = self.query_one(f"#{_TABLE_ID}", DataTable)
        table.clear()
        query = self.query_one(f"#{_FILTER_ID}", Input).value.strip().lower()
        for tone in self._tones:
            if query and query not in tone.name.lower():
                continue
            table.add_row(tone.name, tone.guitar or "", _SYNC_GLYPH[tone.sync], key=tone.tone_id)

    def action_refresh(self) -> None:
        self.refresh_tones()

    def action_focus_filter(self) -> None:
        self.query_one(f"#{_FILTER_ID}", Input).focus()

    def action_clear_filter(self) -> None:
        filter_input = self.query_one(f"#{_FILTER_ID}", Input)
        filter_input.value = ""  # triggers Input.Changed -> _on_filter_changed -> rebuild
        self.query_one(f"#{_TABLE_ID}", DataTable).focus()

    @on(Input.Changed, f"#{_FILTER_ID}")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tone_id = event.row_key.value
        tone = self.app.core.library.get_tone(tone_id)
        if tone is not None:
            self.app.push_screen(ToneDetailModal(tone))

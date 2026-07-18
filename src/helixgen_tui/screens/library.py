"""LibraryScreen: browse the tone library and drive make-active / sync-tone.

Read paths (table, detail modal, filter) stay pure-local. The two device
actions go through the app's ``DeviceService``: ``a`` makes a tone active
(instant for an already-synced tone; a confirm-then-install-then-activate flow
for a local-only one), ``s`` syncs a tone. When offline both refuse up front —
no port call, no modal — and say so in the footer.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.coordinate import Coordinate
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from helixgen_tui.core.models import MutationPlan, OpResult, SyncState, ToneVM
from helixgen_tui.screens.base import LibrarianScreen
from helixgen_tui.widgets.confirm_modal import ConfirmModal

_SYNC_GLYPH = {
    SyncState.SYNCED: "✓",  # check mark
    SyncState.LOCAL_ONLY: "○",  # white circle
    SyncState.UNKNOWN: "?",
}

_FILTER_ID = "library-filter"
_TABLE_ID = "library-table"


class ActivateToneRequested(Message):
    """Screen-internal hand-off: launch the make-active worker on the UI thread.

    Posted from the install-then-activate chain's ``done`` callback, which under
    the production thread spawn runs on a worker thread — where calling
    ``DeviceService.run`` (``App.run_worker``) directly would be unsafe. The
    handler runs on the UI thread; ``post_message`` is thread-safe and, under
    the synchronous test spawn, simply queues for the next event-loop tick (no
    ``call_from_thread`` self-deadlock)."""

    def __init__(self, tone_id: str) -> None:
        self.tone_id = tone_id
        super().__init__()


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
    """Library-mode screen: browse tones, view details, filter, refresh, activate, sync."""

    TAB_LABEL = "Library"
    MODE_NAME = "library"

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("a", "make_active", "Activate"),
        Binding("s", "sync_tone", "Sync"),
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
        super().on_mount()  # seed the footer from the app's device state
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

    def on_screen_resume(self) -> None:
        """Re-read the library each time this (singleton) mode screen is shown
        again — on_mount only fires once, so without this a tone appended while
        another tab was active would never appear on return."""
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

    # -- device actions ----------------------------------------------------

    def _selected_tone(self) -> ToneVM | None:
        """The tone under the table cursor, or None on an empty/filtered table."""
        table = self.query_one(f"#{_TABLE_ID}", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return self.app.core.library.get_tone(row_key.value)

    def _activate(self, tone_id: str) -> None:
        """Launch the make-active worker. Always called on the UI thread (a key
        action, or the ActivateToneRequested handler)."""
        device = self.app.core.device
        self.app.device_service.run(
            "make_active",
            lambda: device.make_active(tone_id),
            self.app.report_op,
        )

    def action_make_active(self) -> None:
        tone = self._selected_tone()
        if tone is None or self._offline():
            return
        if tone.sync == SyncState.SYNCED:
            self._activate(tone.tone_id)
            return
        # Local-only: confirm, then install (sync) the tone before activating it.
        plan = MutationPlan(
            title="Install tone on the device?",
            lines=(
                f"{tone.name} is local-only — not on the Helix yet.",
                "Installing will sync it to the device, then make it active.",
            ),
        )
        self.app.push_screen(ConfirmModal(plan), lambda ok: self._install_then_activate(tone, ok))

    def _install_then_activate(self, tone: ToneVM, confirmed: bool | None) -> None:
        if not confirmed:
            return
        device = self.app.core.device
        tone_id = tone.tone_id

        def _after_sync(result: OpResult) -> None:
            # Runs on a worker thread under the production spawn — must not call
            # App.run_worker directly. Hop to the UI thread for the follow-up.
            self.app.report_op(result)
            if result.ok:
                self.post_message(ActivateToneRequested(tone_id))

        self.app.device_service.run("sync_tone", lambda: device.sync_tone(tone_id), _after_sync)

    def on_activate_tone_requested(self, message: ActivateToneRequested) -> None:
        self._activate(message.tone_id)

    def action_sync_tone(self) -> None:
        tone = self._selected_tone()
        if tone is None or self._offline():
            return
        device = self.app.core.device
        tone_id = tone.tone_id
        self.app.device_service.run(
            "sync_tone",
            lambda: device.sync_tone(tone_id),
            self.app.report_op,
        )

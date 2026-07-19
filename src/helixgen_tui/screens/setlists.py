"""SetlistsScreen: browse setlists, edit membership/order, drive sync.

Left pane lists every setlist (name + sync-enabled glyph); right pane shows
the tones of whichever setlist the left cursor is on, in manifest order.
Membership edits (``a`` add, ``d`` remove, ``J``/``K`` reorder) are local
``SetlistPort`` mutations — no device involved, no offline guard — and the
screen re-renders the new order itself from the ``OpResult`` rather than
re-reading the port (mirrors how ``RealSetlists`` persists the change: the
port call is the source of truth, this is just an optimistic local echo of
it). ``S``/``A`` are the two device actions: ``S`` syncs the selected setlist
instantly, ``A`` confirms ``plan_sync_all`` before syncing every setlist —
both refuse up front when offline, exactly like LibraryScreen's device
actions. ``A`` reads its plan via ``DeviceService.query`` (like
``screens/irs.py``'s prune/delete plans) rather than calling the port
directly, opening the ConfirmModal from the plan-ready handler once it
arrives.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from helixgen_tui.core.device import QueryResult
from helixgen_tui.core.models import MutationPlan, OpResult, SetlistVM, ToneVM
from helixgen_tui.screens.base import LibrarianScreen
from helixgen_tui.screens.filterable import FilterableTableMixin
from helixgen_tui.widgets.confirm_modal import ConfirmModal

_SETLIST_TABLE_ID = "setlists-table"
_TONES_TABLE_ID = "setlist-tones-table"
_FILTER_ID = "setlists-filter"
_LEFT_PANE_ID = "setlists-left-pane"


class AddToneModal(ModalScreen[str | None]):
    """Modal picker: library tones not already in the target setlist.

    ``enter`` on a row dismisses with that tone's id; ``escape`` dismisses
    with ``None``.
    """

    DEFAULT_CSS = """
    AddToneModal {
        align: center middle;
    }

    AddToneModal > Container {
        width: 60;
        height: 16;
        padding: 1 2;
        border: round $primary;
        background: $panel;
    }

    AddToneModal DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, tones: list[ToneVM]) -> None:
        self._tones = tones
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Add tone — enter to pick, escape to cancel")
            yield DataTable(cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Tone")
        for tone in self._tones:
            table.add_row(Text(tone.name), key=tone.tone_id)
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(event.row_key.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


# Module-level Message (not nested — see app.py's DeviceStateChanged for why):
# a UI-thread hand-off from a DeviceService `done` callback, which under the
# production thread-worker spawn runs off-thread, where opening a modal
# directly would be unsafe.
class SyncAllPlanReady(Message):
    """Posted from the ``plan_sync_all`` query's ``done`` callback: push the
    ConfirmModal on the UI thread once the plan arrives."""

    def __init__(self, result: QueryResult) -> None:
        self.result = result
        super().__init__()


class SetlistsScreen(FilterableTableMixin, LibrarianScreen):
    """Setlists-mode screen: membership, ordering, and sync."""

    TAB_LABEL = "Setlists"
    MODE_NAME = "setlists"

    filter_input_id = _FILTER_ID
    filter_table_id = _SETLIST_TABLE_ID

    DEFAULT_CSS = f"""
    SetlistsScreen Horizontal {{
        height: 1fr;
    }}

    SetlistsScreen #{_LEFT_PANE_ID} {{
        width: 1fr;
        height: 100%;
    }}

    SetlistsScreen #{_SETLIST_TABLE_ID} {{
        width: 100%;
        height: 1fr;
    }}

    SetlistsScreen #{_TONES_TABLE_ID} {{
        width: 2fr;
        height: 100%;
    }}
    """

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("a", "add_tone", "Add tone"),
        Binding("d", "remove_tone", "Remove tone"),
        Binding("J", "move_down", "Move down"),
        Binding("K", "move_up", "Move up"),
        Binding("S", "sync_setlist", "Sync"),
        Binding("A", "sync_all", "Sync all"),
        Binding("slash", "focus_filter", "Filter", key_display="/"),
        Binding("escape", "clear_filter", "Clear", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setlists: list[SetlistVM] = []
        # Local working copy of each setlist's tone-id order. Mutated in place
        # on a successful add/remove/move OpResult so the right pane updates
        # immediately, without a round trip back through list_setlists().
        self._tone_order: dict[str, list[str]] = {}
        # Name of the setlist the tones pane last rendered. Guards the tones
        # cursor restore so it only fires when the pane is rebuilt for the same
        # setlist (a ScreenResume re-render); switching setlists resets to top.
        self._tones_setlist_name: str | None = None

    def body(self) -> ComposeResult:
        with Horizontal():
            # The filter belongs to the left pane only, so it is stacked above
            # that table rather than spanning both panes.
            with Vertical(id=_LEFT_PANE_ID):
                yield Input(placeholder="filter", id=_FILTER_ID)
                yield DataTable(id=_SETLIST_TABLE_ID, cursor_type="row")
            yield DataTable(id=_TONES_TABLE_ID, cursor_type="row")

    def on_mount(self) -> None:
        super().on_mount()  # seed the footer from the app's device state
        self.query_one(f"#{_SETLIST_TABLE_ID}", DataTable).add_columns("Setlist", "Sync")
        self.query_one(f"#{_TONES_TABLE_ID}", DataTable).add_columns("Tone")
        self.refresh_setlists()
        self.query_one(f"#{_SETLIST_TABLE_ID}", DataTable).focus()

    def refresh_setlists(self) -> None:
        """Re-read setlists from core.setlists and rebuild both panes."""
        self._setlists = self.app.core.setlists.list_setlists()
        self._tone_order = {sl.name: list(sl.tones) for sl in self._setlists}
        self._rebuild_setlist_table()
        self._rebuild_tones_table()

    def action_refresh(self) -> None:
        self.refresh_setlists()

    def on_screen_resume(self) -> None:
        """Re-read on every return to this (singleton) mode screen — on_mount
        fires once, so a setlist added elsewhere would otherwise stay hidden."""
        self.refresh_setlists()

    def _rebuild_setlist_table(self) -> None:
        self.rebuild_filtered()

    # -- FilterableTableMixin hooks ----------------------------------------

    def filter_items(self) -> list[SetlistVM]:
        return self._setlists

    def filter_text(self, item: SetlistVM) -> str:
        return item.name

    def filter_row(self, item: SetlistVM, label: Text) -> tuple[object, ...]:
        return (label, "✓" if item.sync_enabled else "○")

    def filter_row_key(self, item: SetlistVM) -> str:
        return item.name

    def filter_on_enter(self, item: SetlistVM) -> None:
        """Enter in the filter jumps the left cursor to the best match and
        stops there — the tones pane follows via RowHighlighted. Syncing stays
        on ``S`` / ``A``: a device write is never a side effect of searching."""
        self.move_cursor_to(item)

    def action_focus_filter(self) -> None:
        self.query_one(f"#{_FILTER_ID}", Input).focus()

    def action_clear_filter(self) -> None:
        filter_input = self.query_one(f"#{_FILTER_ID}", Input)
        filter_input.value = ""  # triggers Input.Changed -> rebuild
        self.query_one(f"#{_SETLIST_TABLE_ID}", DataTable).focus()

    @on(Input.Changed, f"#{_FILTER_ID}")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_setlist_table()
        # Re-ranking can put a different setlist under an unmoved cursor, which
        # fires no RowHighlighted — rebuild the right pane explicitly.
        self._rebuild_tones_table()

    @on(Input.Submitted, f"#{_FILTER_ID}")
    def _on_filter_submitted(self, event: Input.Submitted) -> None:
        self.handle_filter_submitted()

    def _rebuild_tones_table(self) -> None:
        table = self.query_one(f"#{_TONES_TABLE_ID}", DataTable)
        setlist = self._selected_setlist()
        # Preserve the tones cursor only across a same-setlist rebuild (the
        # ScreenResume case, #8a). Switching to a different setlist resets the
        # right pane to the top — restoring by tone_id there would wrongly stick
        # the cursor to a tone the two setlists happen to share.
        same_setlist = setlist is not None and setlist.name == self._tones_setlist_name
        prev_key = self._capture_cursor_key(table) if same_setlist else None
        table.clear()
        self._tones_setlist_name = setlist.name if setlist is not None else None
        if setlist is None:
            return
        for tone_id in self._tone_order.get(setlist.name, []):
            tone = self.app.core.library.get_tone(tone_id)
            name = tone.name if tone is not None else tone_id
            table.add_row(Text(name), key=tone_id)
        self._restore_cursor_key(table, prev_key)

    @on(DataTable.RowHighlighted, f"#{_SETLIST_TABLE_ID}")
    def _on_setlist_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._rebuild_tones_table()

    # -- selection helpers ---------------------------------------------------

    def _selected_setlist(self) -> SetlistVM | None:
        """The setlist under the left table's cursor, or None on an empty table.

        Resolved through the mixin's visible list, not by parsing row keys, so
        a ranked/filtered pane never maps a cursor row to the wrong setlist."""
        return self.selected()

    def _selected_tone_id(self) -> str | None:
        """The tone id under the right table's cursor, or None on an empty table."""
        table = self.query_one(f"#{_TONES_TABLE_ID}", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return row_key.value

    # -- membership: add / remove / reorder ----------------------------------

    def action_add_tone(self) -> None:
        setlist = self._selected_setlist()
        if setlist is None:
            return
        current = set(self._tone_order.get(setlist.name, []))
        candidates = [
            tone for tone in self.app.core.library.list_tones() if tone.tone_id not in current
        ]
        name = setlist.name
        self.app.push_screen(AddToneModal(candidates), lambda tone_id: self._do_add(name, tone_id))

    def _do_add(self, setlist_name: str, tone_id: str | None) -> None:
        if tone_id is None:  # cancelled
            return
        result = self.app.core.setlists.add_tone(setlist_name, tone_id)
        self.app.report_op(result)
        if result.ok:
            self._tone_order.setdefault(setlist_name, []).append(tone_id)
            self._rebuild_tones_table()

    def action_remove_tone(self) -> None:
        setlist = self._selected_setlist()
        tone_id = self._selected_tone_id()
        if setlist is None or tone_id is None:
            return
        result = self.app.core.setlists.remove_tone(setlist.name, tone_id)
        self.app.report_op(result)
        if result.ok:
            order = self._tone_order.get(setlist.name, [])
            if tone_id in order:
                order.remove(tone_id)
            self._rebuild_tones_table()

    def _move(self, delta: int) -> None:
        setlist = self._selected_setlist()
        tone_id = self._selected_tone_id()
        if setlist is None or tone_id is None:
            return
        order = self._tone_order.get(setlist.name, [])
        if tone_id not in order:
            return
        index = order.index(tone_id)
        target = index + delta
        if not 0 <= target < len(order):
            # Already at the edge: nothing would move. Skip the port call
            # entirely — calling it here would report a misleading "ok" for
            # a no-op move (FakeSetlistPort always answers ok=True).
            return
        result = self.app.core.setlists.move_tone(setlist.name, tone_id, delta)
        self.app.report_op(result)
        if not result.ok:
            return
        order[index], order[target] = order[target], order[index]
        self._rebuild_tones_table()
        self.query_one(f"#{_TONES_TABLE_ID}", DataTable).move_cursor(row=target)

    def action_move_down(self) -> None:
        self._move(1)

    def action_move_up(self) -> None:
        self._move(-1)

    # -- device actions: sync one / sync all ---------------------------------

    def action_sync_setlist(self) -> None:
        setlist = self._selected_setlist()
        if setlist is None or self._offline():
            return
        device = self.app.core.device
        name = setlist.name
        self.app.device_service.run(
            "sync_setlist",
            lambda: device.sync_setlist(name, False),
            self.app.report_op,
        )

    def action_sync_all(self) -> None:
        if self._offline():
            return
        device = self.app.core.device
        self.app.device_service.query(
            "plan_sync_all",
            lambda: device.plan_sync_all(False),
            lambda result: self.post_message(SyncAllPlanReady(result)),
        )

    def on_sync_all_plan_ready(self, message: SyncAllPlanReady) -> None:
        if not message.result.ok or message.result.value is None:
            self.app.report_op(
                OpResult(
                    ok=False,
                    message=message.result.message or "could not load sync-all plan",
                )
            )
            return
        plan: MutationPlan = message.result.value  # type: ignore[assignment]
        self.app.push_screen(ConfirmModal(plan), self._confirm_sync_all)

    def _confirm_sync_all(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        device = self.app.core.device
        self.app.device_service.run(
            "sync_all",
            lambda: device.sync_all(False),
            self.app.report_op,
        )

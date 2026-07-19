"""Shared filter/rank/highlight wiring for a filter Input over a DataTable.

A mixin, not a base class: it serves both ``LibrarianScreen`` subclasses and
``ModalScreen`` modals, which share no common ancestor of ours.

The mixin owns ``_visible`` — the ordered list of items currently displayed,
mirroring the table's rows 1:1. Hosts resolve the selected item through
``selected()``, never by parsing row keys. This is what lets the IR panes
filter safely despite duplicate display names.
"""

from __future__ import annotations

from typing import Any, Sequence

from rich.text import Text
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input
from textual.widgets.data_table import RowDoesNotExist

from helixgen_tui.fuzzy import match

HIGHLIGHT_STYLE = "bold"


def capture_cursor_key(table: DataTable) -> str | None:
    """The row key under the table cursor, or None on an empty table.

    Captured before a ``clear()``/rebuild so the cursor can be restored to the
    same row afterward — a ScreenResume rebuild would otherwise snap it back to
    row 0 (cosmetic noise; #8a). Only for tables whose keys are real identities
    (the setlist tones pane, keyed by ``tone_id``); the mixin itself restores by
    item, because its own keys may be positional."""
    if table.row_count == 0:
        return None
    return table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value


def restore_cursor_key(table: DataTable, key: str | None) -> None:
    """Move the cursor back to the row with ``key`` after a rebuild.

    No-op (cursor stays at row 0) when nothing was captured or the row is gone
    after the rebuild — the graceful fall-back for a filtered-out or deleted
    row."""
    if key is None:
        return
    try:
        index = table.get_row_index(key)
    except RowDoesNotExist:
        return
    table.move_cursor(row=index)


class FilterableTableMixin:
    """Wire a filter ``Input`` to a ``DataTable`` with scored fuzzy filtering.

    Hosts set ``filter_input_id`` / ``filter_table_id`` and override:

      - ``filter_items() -> Sequence[Any]``   backing source list, native order
      - ``filter_text(item) -> str``          primary text to match + highlight
      - ``filter_row(item, label) -> tuple``  cells for the row, given the
        pre-highlighted primary label
      - ``filter_row_key(item, position) -> str | None``  stable key, or None
        for no key; ``position`` is the item's index in the *backing* list, for
        hosts whose items carry no natural identifier
      - ``filter_on_enter(item) -> None``     primary action on the top hit
        (defaults to moving the cursor there)

    Hosts also hook ``Input.Changed`` -> ``rebuild_filtered()`` and
    ``Input.Submitted`` -> ``handle_filter_submitted()``.
    """

    filter_input_id: str
    filter_table_id: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._visible: list[Any] = []
        super().__init__(*args, **kwargs)

    # -- host hooks --------------------------------------------------------

    def filter_items(self) -> Sequence[Any]:
        raise NotImplementedError

    def filter_text(self, item: Any) -> str:
        raise NotImplementedError

    def filter_row(self, item: Any, label: Text) -> tuple[Any, ...]:
        raise NotImplementedError

    def filter_row_key(self, item: Any, position: int) -> str | None:
        raise NotImplementedError

    def filter_on_enter(self, item: Any) -> None:
        """Park the table cursor on ``item`` and stop there.

        The default for every browse surface: activate/sync/push/delete/rename
        keep their own keys, so a device write is never a side effect of
        searching. Only a picker whose whole purpose is committing a choice
        (``AddToneModal``) overrides this."""
        self.move_cursor_to(item)

    # -- the wiring --------------------------------------------------------

    def filter_query(self) -> str:
        return self.query_one(f"#{self.filter_input_id}", Input).value.strip()

    def filter_table(self) -> DataTable:
        return self.query_one(f"#{self.filter_table_id}", DataTable)

    def rebuild_filtered(self) -> None:
        """Filter, rank, highlight, rebuild the table, place the cursor.

        With a query the cursor lands on the top hit: it is what Enter acts on,
        so anything else would highlight one row and commit another. With no
        query the cursor follows the item it was on, by identity through
        ``_visible`` — never by row key, which is positional on the IR panes and
        would name a different IR after the backing list changes."""
        table = self.filter_table()
        previous_item = self.selected()
        query = self.filter_query()

        scored: list[tuple[int, int, Any, tuple[int, ...]]] = []
        for position, item in enumerate(self.filter_items()):
            result = match(query, self.filter_text(item))
            if result is None:
                continue
            scored.append((result.score, position, item, result.indices))

        # -score for best-first; position keeps native order stable within a tie.
        # An empty query scores every item 0, so this reproduces native order.
        scored.sort(key=lambda row: (-row[0], row[1]))

        self._visible = []
        table.clear()
        for _score, position, item, indices in scored:
            label = Text(self.filter_text(item))
            for index in indices:
                label.stylize(HIGHLIGHT_STYLE, index, index + 1)
            key = self.filter_row_key(item, position)
            table.add_row(*self.filter_row(item, label), key=key)
            self._visible.append(item)

        if query:
            table.move_cursor(row=0)
        elif previous_item is not None:
            # No-op when the item is gone (deleted, or filtered out by another
            # pane's rebuild) — the cursor then stays at row 0.
            self.move_cursor_to(previous_item)

    def selected(self) -> Any | None:
        """The item under the cursor, resolved through the visible list."""
        table = self.filter_table()
        row = table.cursor_row
        if row is None or not (0 <= row < len(self._visible)):
            return None
        return self._visible[row]

    def move_cursor_to(self, item: Any) -> None:
        """Put the table cursor on ``item``'s row. No-op if it is not visible."""
        try:
            index = self._visible.index(item)
        except ValueError:
            return
        self.filter_table().move_cursor(row=index)

    def handle_filter_submitted(self) -> None:
        """Enter in the filter input: act on the row under the cursor, if any.

        Always the cursor row, never ``_visible[0]`` directly: a query parks the
        cursor on the top hit in ``rebuild_filtered``, so the two agree there,
        and where they could diverge (the user moved the cursor) what the user
        sees highlighted is what Enter acts on."""
        item = self.selected()
        if item is None:
            return
        self.filter_on_enter(item)

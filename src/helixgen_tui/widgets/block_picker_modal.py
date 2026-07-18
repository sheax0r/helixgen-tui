"""BlockPickerModal: a two-step category -> model picker for add/swap.

Opened by the tone editor's ``a`` (add block) and swap affordance. First lists
the block categories from the library catalogue; ``enter`` on a category drills
into its models; ``enter`` on a model dismisses with that model id. ``escape``
backs out of the model list to the categories, or cancels (``None``) from the
category list.

Markup safety (repo bug class #12): every category/model cell is a
``rich.text.Text`` so a bracket-bearing model id/display renders literally
instead of being stripped or crashing the table.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from helixgen_tui.core.models import BlockCatalogVM


class BlockPickerModal(ModalScreen[str | None]):
    """Pick a block model: category list, then its models. Dismisses with the
    chosen ``model_id`` (or ``None`` on cancel)."""

    DEFAULT_CSS = """
    BlockPickerModal {
        align: center middle;
    }

    BlockPickerModal > Container {
        width: 60;
        height: 18;
        padding: 1 2;
        border: round $primary;
        background: $panel;
    }

    BlockPickerModal DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Back/Cancel", show=False)]

    def __init__(self, catalog: tuple[BlockCatalogVM, ...]) -> None:
        self._catalog = catalog
        self._category: BlockCatalogVM | None = None  # None = showing categories
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("", id="block-picker-title", markup=False)
            yield DataTable(cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Name")
        self._show_categories()
        table.focus()

    def _show_categories(self) -> None:
        self._category = None
        self.query_one("#block-picker-title", Static).update(
            "Add block — pick a category (enter), escape to cancel"
        )
        table = self.query_one(DataTable)
        table.clear()
        for i, cat in enumerate(self._catalog):
            table.add_row(Text(cat.category), key=str(i))

    def _show_models(self, cat: BlockCatalogVM) -> None:
        self._category = cat
        self.query_one("#block-picker-title", Static).update(
            f"{cat.category} — pick a model (enter), escape to go back"
        )
        table = self.query_one(DataTable)
        table.clear()
        for model_id, display in cat.models:
            table.add_row(Text(display), key=model_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if self._category is None:
            # A category was chosen: drill into its models.
            idx = int(key) if key is not None else 0
            self._show_models(self._catalog[idx])
        else:
            # A model was chosen: hand its id back to the editor.
            self.dismiss(key)

    def action_cancel(self) -> None:
        # From the model list, escape backs out to the categories; from the
        # category list it cancels the whole pick.
        if self._category is not None:
            self._show_categories()
        else:
            self.dismiss(None)

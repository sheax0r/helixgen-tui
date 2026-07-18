"""ConfirmModal: a yes/no modal that shows a MutationPlan before a mutating action.

Renders the plan's title and every line verbatim (no reformatting — the plan is
authored by the port that knows what's about to change), then dismisses with
``True`` on ``y`` and ``False`` on ``n``/escape.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from helixgen_tui.core.models import MutationPlan


class ConfirmModal(ModalScreen[bool]):
    """Modal confirming a MutationPlan: ``y`` -> True, ``n``/escape -> False."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }

    ConfirmModal > Container {
        width: auto;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $panel;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, plan: MutationPlan) -> None:
        self._plan = plan
        super().__init__()

    def compose(self) -> ComposeResult:
        plan = self._plan
        body = "\n".join((plan.title, "", *plan.lines, "", "[y] confirm   [n] cancel"))
        with Container():
            yield Static(body)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

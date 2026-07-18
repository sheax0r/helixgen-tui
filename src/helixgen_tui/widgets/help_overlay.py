"""HelpOverlay: modal screen listing key bindings, opened with ``?`` and closed with escape."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

HELP_TEXT = """\
helixgen-tui — key bindings

  1        Library
  2        Setlists
  3        IRs
  4        Device
  ?        Show this help
  q        Quit
  escape   Close this help
"""


class HelpOverlay(ModalScreen[None]):
    """Modal overlay listing the app's key bindings."""

    DEFAULT_CSS = """
    HelpOverlay {
        align: center middle;
    }

    HelpOverlay > Container {
        width: auto;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $panel;
    }
    """

    BINDINGS = [Binding("escape", "dismiss_help", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(HELP_TEXT)

    def action_dismiss_help(self) -> None:
        self.dismiss()

"""HelixgenTuiApp: the top-level Textual application — tabbed modes, footer, help overlay."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from helixgen_tui.core.ports import Core
from helixgen_tui.screens.base import LibrarianScreen
from helixgen_tui.screens.library import LibraryScreen
from helixgen_tui.widgets.help_overlay import HelpOverlay

# Ordered (key, mode_name, label) tuples shared by every screen's TabStrip.
MODE_TABS: list[tuple[str, str, str]] = [
    ("1", "library", "Library"),
    ("2", "setlists", "Setlists"),
    ("3", "irs", "IRs"),
    ("4", "device", "Device"),
]


class SetlistsScreen(LibrarianScreen):
    """Placeholder setlists-mode screen (real content lands in a later task)."""

    TAB_LABEL = "Setlists"
    MODE_NAME = "setlists"

    def body(self) -> ComposeResult:
        yield Static("Setlists")


class IrsScreen(LibrarianScreen):
    """Placeholder IRs-mode screen (real content lands in a later task)."""

    TAB_LABEL = "IRs"
    MODE_NAME = "irs"

    def body(self) -> ComposeResult:
        yield Static("IRs")


class DeviceScreen(LibrarianScreen):
    """Placeholder device-mode screen (real content lands in a later task)."""

    TAB_LABEL = "Device"
    MODE_NAME = "device"

    def body(self) -> ComposeResult:
        yield Static("Device")


class HelixgenTuiApp(App):
    """The helixgen-tui shell: tabbed modes, status footer, help overlay."""

    TITLE = "helixgen-tui"

    MODE_TABS = MODE_TABS

    MODES = {
        "library": LibraryScreen,
        "setlists": SetlistsScreen,
        "irs": IrsScreen,
        "device": DeviceScreen,
    }
    DEFAULT_MODE = "library"

    BINDINGS = [
        Binding("1", "switch_mode('library')", "Library"),
        Binding("2", "switch_mode('setlists')", "Setlists"),
        Binding("3", "switch_mode('irs')", "IRs"),
        Binding("4", "switch_mode('device')", "Device"),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, core: Core) -> None:
        """`core` is the app's single entry point into the data layer.

        Every screen reaches it via ``self.app.core`` — screens never import
        helixgen directly (enforced by tests/test_boundaries.py).
        """
        self.core = core
        super().__init__()

    def action_show_help(self) -> None:
        self.push_screen(HelpOverlay())

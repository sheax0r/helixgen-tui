"""LibrarianScreen: base class for the app's top-level tabbed screens."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer

from helixgen_tui.core.models import OpResult
from helixgen_tui.screens.filterable import capture_cursor_key, restore_cursor_key
from helixgen_tui.widgets.status_footer import StatusFooter
from helixgen_tui.widgets.tab_strip import TabStrip

_OFFLINE_MSG = "device offline — connect on the Device tab (4) first"


class LibrarianScreen(Screen):
    """Base class for the four top-level mode screens (library, setlists, irs, device).

    Subclasses set ``TAB_LABEL`` and ``MODE_NAME``, and override ``body()`` to
    yield the screen's main content. ``compose()`` wraps that content with the
    shared ``TabStrip`` (top) and ``StatusFooter`` (bottom).
    """

    TAB_LABEL: str = ""
    MODE_NAME: str = ""

    DEFAULT_CSS = """
    LibrarianScreen #bottom-bars {
        dock: bottom;
        height: 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield TabStrip(tabs=self.app.MODE_TABS, active_mode=self.MODE_NAME)
        yield from self.body()
        # Both bottom bars share one docked container: docking them to the
        # screen edge individually would stack them on the same row (the
        # bindings footer painted over the status bar). Status above, keys at
        # the very bottom edge.
        with Vertical(id="bottom-bars"):
            yield StatusFooter()
            # Textual's bindings footer: shows this screen's keys and triggers
            # them on click — the visible/mouse counterpart to the ? overlay.
            yield Footer()

    def body(self) -> ComposeResult:
        """Compose hook: subclasses yield the screen's main content here."""
        raise NotImplementedError

    def on_mount(self) -> None:
        """Seed this screen's fresh footer from the app's current device state,
        so switching modes never resets a connected footer back to offline."""
        footer = self.query_one(StatusFooter)
        footer.set_device_text(self.app.device_text)
        if self.app.last_action:
            footer.set_last_action(self.app.last_action)

    # The capture/restore pair lives in ``screens.filterable`` so the filter
    # mixin — which serves modals that are not LibrarianScreens — can reach it
    # without duplicating the logic. Kept here as delegating statics because
    # every mode screen already calls them by these names.
    _capture_cursor_key = staticmethod(capture_cursor_key)
    _restore_cursor_key = staticmethod(restore_cursor_key)

    def _offline(self, message: str | None = None) -> bool:
        """True (and reports it to the footer) when no device is connected —
        actions refuse here without ever touching the port. Shared by every
        mode screen so the offline-refusal check and message live in one
        place; pass ``message`` to override the default footer text for a
        screen whose refusal reads differently (see ``DeviceScreen``)."""
        service = self.app.device_service
        if service is None or service.state.status != "connected":
            self.app.report_op(OpResult(ok=False, message=message or _OFFLINE_MSG))
            return True
        return False

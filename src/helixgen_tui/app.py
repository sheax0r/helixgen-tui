"""HelixgenTuiApp: the top-level Textual application — tabbed modes, footer, help overlay.

The app owns the single ``DeviceService`` and routes its updates to whichever
mode screen's ``StatusFooter`` is on top: device-state changes become the
footer's left-hand text, and every ``OpResult`` from a device action becomes the
right-hand last-action text. Both hop onto the UI thread via ``post_message`` so
the thread-worker ``spawn`` can call back safely; tests inject a synchronous
``spawn`` and the same messages flush deterministically on ``pilot.pause()``.
"""

from __future__ import annotations

from typing import Callable

from textual.app import App
from textual.binding import Binding
from textual.message import Message

from helixgen_tui.core.device import DeviceService
from helixgen_tui.core.models import DeviceStateVM, OpResult
from helixgen_tui.core.ports import Core
from helixgen_tui.screens.device import DeviceScreen
from helixgen_tui.screens.irs import IrsScreen
from helixgen_tui.screens.library import LibraryScreen
from helixgen_tui.screens.setlists import SetlistsScreen
from helixgen_tui.widgets.help_overlay import HelpOverlay
from helixgen_tui.widgets.status_footer import DEFAULT_DEVICE_TEXT, StatusFooter

# Ordered (key, mode_name, label) tuples shared by every screen's TabStrip.
MODE_TABS: list[tuple[str, str, str]] = [
    ("1", "library", "Library"),
    ("2", "setlists", "Setlists"),
    ("3", "irs", "IRs"),
    ("4", "device", "Device"),
]


# Module-level Messages (not nested): a nested class would take a Textual
# namespace from its enclosing class, so the handler would have to be named
# `on_helixgentuiapp_device_state_changed`; at module scope the handler is the
# plain `on_device_state_changed`.
class DeviceStateChanged(Message):
    """Posted (thread-safely) when the DeviceService observes a new state."""

    def __init__(self, state: DeviceStateVM) -> None:
        self.state = state
        super().__init__()


class DeviceOpFinished(Message):
    """Posted (thread-safely) when a device action returns an OpResult."""

    def __init__(self, result: OpResult) -> None:
        self.result = result
        super().__init__()


def format_device_text(vm: DeviceStateVM) -> str:
    """Footer left-hand text for a device state: glyph + status, model when
    known, and any extra ``detail`` the port supplied (skipping a detail that's
    just another rendering of the offline line)."""
    if vm.status == "connected":
        text = "device: ● connected"
        if vm.model:
            text = f"{text} · {vm.model}"
    elif vm.status == "connecting":
        text = "device: ◐ connecting"
    else:
        text = DEFAULT_DEVICE_TEXT  # "device: ○ offline"
    detail = (vm.detail or "").strip()
    if detail and not detail.startswith("device:") and detail not in text:
        text = f"{text} · {detail}"
    return text




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

    def __init__(
        self,
        core: Core,
        device_spawn: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        """``core`` is the app's single entry point into the data layer.

        Every screen reaches it via ``self.app.core`` — screens never import
        helixgen directly (enforced by tests/test_boundaries.py). ``device_spawn``
        overrides how the DeviceService runs blocking work; tests pass a
        synchronous runner, production defaults to a Textual thread-worker.
        """
        self.core = core
        self._device_spawn = device_spawn
        self._device_text = DEFAULT_DEVICE_TEXT
        self._last_action = ""
        self.device_service: DeviceService | None = None
        super().__init__()

    def on_mount(self) -> None:
        spawn = self._device_spawn if self._device_spawn is not None else self._worker_spawn
        self.device_service = DeviceService(
            self.core.device,
            on_state=lambda state: self.post_message(DeviceStateChanged(state)),
            spawn=spawn,
        )
        self.device_service.start()
        self.set_interval(self.device_service.poll_interval, self.device_service.retry_now)

    def _worker_spawn(self, fn: Callable[[], None]) -> None:
        """Default spawn: run blocking device work on a Textual thread-worker so
        it stays off the UI event loop and is torn down with the app."""
        self.run_worker(fn, thread=True, exit_on_error=False)

    # -- footer plumbing ---------------------------------------------------

    @property
    def device_text(self) -> str:
        return self._device_text

    @property
    def last_action(self) -> str:
        return self._last_action

    def _active_footer(self) -> StatusFooter | None:
        """The StatusFooter of the topmost mode screen that has one (modals
        don't), or None before the first screen mounts."""
        for screen in reversed(self.screen_stack):
            try:
                return screen.query_one(StatusFooter)
            except Exception:  # noqa: BLE001 — no footer on this screen; keep looking
                continue
        return None

    def set_footer_device_text(self, text: str) -> None:
        self._device_text = text
        footer = self._active_footer()
        if footer is not None:
            footer.set_device_text(text)

    def report_op(self, result: OpResult) -> None:
        """Route a device OpResult to the footer's last-action text (thread-safe)."""
        self.post_message(DeviceOpFinished(result))

    def on_device_state_changed(self, message: DeviceStateChanged) -> None:
        self.set_footer_device_text(format_device_text(message.state))

    def on_device_op_finished(self, message: DeviceOpFinished) -> None:
        self._last_action = message.result.message
        footer = self._active_footer()
        if footer is not None:
            footer.set_last_action(message.result.message)

    def action_show_help(self) -> None:
        self.push_screen(HelpOverlay())

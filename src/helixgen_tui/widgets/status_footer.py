"""StatusFooter: persistent bottom bar showing device connection state and the last action."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

DEFAULT_DEVICE_TEXT = "device: ○ offline"


class StatusFooter(Static):
    """Bottom status bar: device connection state plus the most recent action message."""

    DEFAULT_CSS = """
    StatusFooter {
        height: 1;
        width: 100%;
        background: $panel;
        color: $text;
    }
    """

    device_text: reactive[str] = reactive(DEFAULT_DEVICE_TEXT)
    last_action: reactive[str] = reactive("")

    def set_device_text(self, text: str) -> None:
        """Update the device connection status text (left side of the footer)."""
        self.device_text = text

    def set_last_action(self, text: str) -> None:
        """Update the last-action message text (right side of the footer)."""
        self.last_action = text

    def render(self) -> Text:
        # Return a rich Text (never a str): device- and now user-derived text
        # (a rejected manual-entry value, a bracketed tone name) flows through
        # last_action, and a Static str is console-markup-parsed — a `[/]` or
        # `[reverb]` would be stripped or crash the whole app (bug class #12).
        # A Text bypasses the markup parse entirely.
        if self.last_action:
            return Text(f"{self.device_text}   {self.last_action}")
        return Text(self.device_text)

    def watch_device_text(self, device_text: str) -> None:
        self.refresh()

    def watch_last_action(self, last_action: str) -> None:
        self.refresh()

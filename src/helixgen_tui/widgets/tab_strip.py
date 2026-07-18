"""TabStrip: the top bar of mode tabs, e.g. ``[1]Library [2]Setlists [3]IRs [4]Device``."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class TabStrip(Static):
    """Renders the app's mode tabs with the active mode highlighted."""

    DEFAULT_CSS = """
    TabStrip {
        height: 1;
        width: 100%;
        background: $panel;
        color: $text;
    }
    """

    active_mode: reactive[str] = reactive("")

    def __init__(self, tabs: list[tuple[str, str, str]], active_mode: str = "", **kwargs) -> None:
        """`tabs` is an ordered list of ``(key, mode_name, label)`` tuples."""
        self._tabs = tabs
        super().__init__(**kwargs)
        self.active_mode = active_mode

    def render(self) -> Text:
        text = Text()
        for index, (key, mode_name, label) in enumerate(self._tabs):
            if index:
                text.append(" ")
            style = "reverse" if mode_name == self.active_mode else ""
            text.append(f"[{key}]{label}", style=style)
        return text

    def watch_active_mode(self, active_mode: str) -> None:
        self.refresh()

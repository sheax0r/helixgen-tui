"""HelpOverlay: modal screen listing key bindings, opened with ``?`` and closed with escape."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

HELP_TEXT = """\
helixgen-tui — key bindings

  Global
    1        Library
    2        Setlists
    3        IRs
    4        Device
    ?        Show this help
    q        Quit
    escape   Close a modal / clear a filter
    /        Fuzzy-filter by name (Library, Setlists, IRs)

    On the browse screens, enter in a filter parks on the
    highlighted match and returns focus to the list — it never
    activates, syncs, pushes, or deletes. Matched characters
    are highlighted; best matches sort first.

  Library
    enter    Open the tone param editor
    a        Make active (installs first if local-only)
    s        Sync tone to device
    r        Refresh
    /        Filter tones (enter parks on the match)

  Tone editor
    up/down  Move selection in the focused pane
    tab      Switch between the chain and params panes
    left/rt  Chain: walk the lane / Params: nudge the value
    enter    Manual entry: type a value, enter to commit
    a        Add a block after the selected one (serial paths)
    x        Remove the selected block (serial paths)
    b        Bypass / enable the selected block
    w        Swap the selected block's model
    s        Save edits to the library file
    escape   Back (confirms if there are unsaved edits)

    Select the output node to edit its level/pan; the input
    node's source is read-only. Add/remove refuse on a
    parallel-routed path.

  Setlists
    a        Add tone to setlist
    d        Remove selected tone
    J        Move tone down
    K        Move tone up
    S        Sync selected setlist
    A        Sync all setlists
    r        Refresh
    /        Filter setlists (enter parks on the match)

    The add-tone picker filters as you type; enter adds the
    best match.

  IRs
    p        Push selected local IR to device
    R        Rename device IR
    d        Delete device IR
    P        Prune device IRs
    r        Refresh
    /        Filter the focused pane (enter parks on
             the match)
    escape   Cancel a rename first, then clear a live
             filter

  Device
    b        Backup
    t        Restore from file
    l        Show lock status
    r        Retry connect
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

"""Placeholder entry point for helixgen-tui.

The actual TUI is deliberately unimplemented: the design spec (backlog #60)
is user-gated and decides the TUI stack (Textual vs urwid vs curses), screen
layout, and navigation before any UI code is written. This module only proves
the packaging: console script, `python -m helixgen_tui`, and version plumbing.
"""

from __future__ import annotations

import sys

from helixgen_tui import __version__

PLACEHOLDER_MESSAGE = (
    f"helixgen-tui {__version__}: the TUI is not yet implemented.\n"
    "The design spec is pending — see docs/BACKLOG.md item #60 in\n"
    "https://github.com/sheax0r/helixgen-tui before any screens are built."
)


def main(argv: list[str] | None = None) -> int:
    """Print the not-yet-implemented placeholder and exit 0."""
    if argv is None:
        argv = sys.argv[1:]
    if "--version" in argv:
        print(__version__)
        return 0
    print(PLACEHOLDER_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

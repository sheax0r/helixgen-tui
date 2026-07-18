"""Entry point for helixgen-tui: `--version`, otherwise launches the Textual app."""

from __future__ import annotations

import sys

from helixgen_tui import __version__


def main(argv: list[str] | None = None) -> int:
    """Print the version with `--version`; otherwise run the TUI to completion."""
    if argv is None:
        argv = sys.argv[1:]
    if "--version" in argv:
        print(__version__)
        return 0

    from helixgen_tui.app import HelixgenTuiApp

    HelixgenTuiApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

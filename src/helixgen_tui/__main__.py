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

    # `build_core()` lives in helixgen_tui.core.real, which wires the ports up
    # to the real helixgen library/device. It's built by a task that may not
    # have merged yet, so the import is deferred to here (never at module
    # import time) and given a clear error if it's still missing.
    try:
        from helixgen_tui.core.real import build_core
    except ImportError as exc:
        raise ImportError(
            "helixgen_tui.core.real.build_core is unavailable — the real Core "
            "adapters haven't landed yet. Cannot launch helixgen-tui without "
            "a Core implementation."
        ) from exc

    HelixgenTuiApp(build_core()).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

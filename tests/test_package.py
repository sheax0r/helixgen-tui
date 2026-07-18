"""Packaging tests: import, version plumbing, and the `--version` flag.

The TUI itself (tabbed modes, footer, help overlay) is exercised in
tests/test_shell.py via Textual's Pilot harness; this module only proves
packaging and version plumbing, not app behavior — so it never launches the
full app (that would block waiting on a real terminal).
"""

from importlib import metadata

import helixgen_tui
from helixgen_tui.__main__ import main


def test_import_exposes_version():
    assert isinstance(helixgen_tui.__version__, str)
    assert helixgen_tui.__version__


def test_version_matches_installed_metadata():
    assert helixgen_tui.__version__ == metadata.version("helixgen-tui")


def test_main_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == helixgen_tui.__version__


def test_main_is_importable():
    assert callable(main)

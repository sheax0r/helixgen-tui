"""Packaging-skeleton tests: import, version plumbing, and the placeholder entry point.

Deliberately no TUI behavior is tested here — none exists yet (backlog #60).
"""

import subprocess
import sys
from importlib import metadata

import helixgen_tui
from helixgen_tui.__main__ import PLACEHOLDER_MESSAGE, main


def test_import_exposes_version():
    assert isinstance(helixgen_tui.__version__, str)
    assert helixgen_tui.__version__


def test_version_matches_installed_metadata():
    assert helixgen_tui.__version__ == metadata.version("helixgen-tui")


def test_main_prints_placeholder(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "not yet implemented" in out
    assert "#60" in out
    assert out.strip() == PLACEHOLDER_MESSAGE


def test_main_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == helixgen_tui.__version__


def test_python_dash_m_entry_point():
    proc = subprocess.run(
        [sys.executable, "-m", "helixgen_tui"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "not yet implemented" in proc.stdout
    assert "#60" in proc.stdout

"""Shared test fixtures: an isolated fake $HELIXGEN_HOME, and a guard that
the real one (~/.helixgen) is never touched by the suite.
"""

from __future__ import annotations

import pathlib

import pytest

_HELIXGEN_ENV_VARS = (
    "HELIXGEN_HOME",
    "HELIXGEN_LIBRARY",
    "HELIXGEN_SETLISTS",
    "HELIXGEN_CACHE",
    "HELIXGEN_PREFS",
    "HELIXGEN_LOCKS",
    "HELIXGEN_IRS",
)


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Point every HELIXGEN_* env var at subdirectories of a throwaway tmp_path.

    Nothing a test does under this fixture can reach the real ~/.helixgen.
    """
    home = tmp_path / "helixgen_home"
    home.mkdir()
    paths = {
        "HELIXGEN_HOME": home,
        "HELIXGEN_LIBRARY": home / "library",
        "HELIXGEN_SETLISTS": home / "setlists",
        "HELIXGEN_CACHE": home / "cache",
        "HELIXGEN_PREFS": home / "preferences.json",
        "HELIXGEN_LOCKS": home / "locks",
        "HELIXGEN_IRS": home / "irs",
    }
    for name, path in paths.items():
        monkeypatch.setenv(name, str(path))
    return home


def _snapshot_real_home() -> dict[str, float] | None:
    """Read-only: file list + mtimes of ~/.helixgen, or None if it doesn't exist."""
    real_home = pathlib.Path.home() / ".helixgen"
    if not real_home.exists():
        return None
    return {str(p): p.stat().st_mtime for p in real_home.rglob("*")}


@pytest.fixture(autouse=True, scope="session")
def _real_home_guard():
    """Fails the session if anything wrote to the developer's real ~/.helixgen.

    Read-only by construction: it only stats files, never creates or
    modifies anything, and is a no-op (before/after both None) when
    ~/.helixgen doesn't exist on the machine running the suite.
    """
    before = _snapshot_real_home()
    yield
    after = _snapshot_real_home()
    assert before == after, (
        "~/.helixgen changed during the test session — a test wrote to the "
        "real home instead of using the tmp_home fixture"
    )

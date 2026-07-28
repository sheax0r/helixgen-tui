"""Shared test fixtures: an isolated fake $HELIXGEN_HOME, and a guard that
the real one ($HELIXGEN_HOME, else ~/.helixgen) is never touched by the suite.
"""

from __future__ import annotations

import os
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


#: The developer's REAL helixgen home, resolved ONCE at import — i.e. before
#: any fixture redirects ``$HELIXGEN_HOME`` (``tmp_home`` per test, the live
#: suite's ``_live_env`` per session). ``$HELIXGEN_HOME`` wins, the same way the
#: engine resolves it: hardcoding ``~/.helixgen`` on a machine with a custom
#: home would snapshot an unrelated directory, so ``before == after`` would hold
#: trivially and the guard would be silently inert.
REAL_HELIXGEN_HOME = pathlib.Path(
    os.environ.get("HELIXGEN_HOME") or pathlib.Path.home() / ".helixgen"
)


def _snapshot_real_home(root: pathlib.Path = REAL_HELIXGEN_HOME) -> dict[str, float] | None:
    """Read-only: file list + mtimes of the real helixgen home, or None if it
    doesn't exist.

    The ``locks/`` subtree is excluded: helixgen's advisory device leases are
    ephemeral cross-process coordination files, and the live suite
    (``tests/live/``) deliberately keeps its lock root REAL so other helixgen
    processes on this machine serialize against it — lease churn there is
    expected, not a state leak.
    """
    if not root.exists():
        return None
    locks = root / "locks"
    return {
        str(p): p.stat().st_mtime
        for p in root.rglob("*")
        if locks not in p.parents and p != locks
    }


@pytest.fixture(autouse=True, scope="session")
def _real_home_guard():
    """Fails the session if anything wrote to the developer's real helixgen home.

    Read-only by construction: it only stats files, never creates or
    modifies anything, and is a no-op (before/after both None) when the home
    doesn't exist on the machine running the suite.

    It cannot tell "a test wrote" from "another helixgen process on this
    machine wrote" — a concurrent CLI/agent session touching the real home
    fails the session too. Confirm which by re-running under an isolated home
    (``HELIXGEN_HOME=$(mktemp -d) uv run pytest``): still failing means the
    suite really did leak.
    """
    before = _snapshot_real_home()
    yield
    after = _snapshot_real_home()
    assert before == after, (
        f"{REAL_HELIXGEN_HOME} changed during the test session — a test wrote "
        "to the real home instead of using the tmp_home fixture"
    )

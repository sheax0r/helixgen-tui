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
).expanduser()

#: The real lease root, resolved with the engine's OWN precedence
#: (``helixgen.locks.locks_root``): ``$HELIXGEN_LOCKS`` WINS over the
#: ``$HELIXGEN_HOME``-derived default. Deriving it from the home alone would
#: exclude the wrong subtree on a machine with a custom lock root.
REAL_LOCKS_ROOT = pathlib.Path(
    os.environ.get("HELIXGEN_LOCKS") or REAL_HELIXGEN_HOME / "locks"
).expanduser()


def _snapshot_real_home(
    root: pathlib.Path = REAL_HELIXGEN_HOME,
    locks: pathlib.Path = REAL_LOCKS_ROOT,
) -> dict[str, float] | None:
    """Read-only: file list + mtimes of the real helixgen home, or None if it
    doesn't exist.

    Two exclusions, both narrow:

    * the lease root: helixgen's advisory device leases are ephemeral
      cross-process coordination files, and the live suite (``tests/live/``)
      deliberately keeps its lock root REAL so other helixgen processes on this
      machine serialize against it — lease churn there is expected, not a leak.
    * ``.git`` metadata: ``~/.helixgen`` is itself a git repo, so any ambient
      ``git status`` (an editor, a shell prompt, a parallel agent session)
      refreshes ``.git/index`` and used to fail the session with a diff of
      nothing but index mtimes. Nothing the suite could leak lives inside
      ``.git/`` — a leaked write lands in the WORKTREE, which is still covered.
    """
    if not root.exists():
        return None
    return {
        str(p): p.stat().st_mtime
        for p in root.rglob("*")
        if locks not in p.parents and p != locks and ".git" not in p.parts
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

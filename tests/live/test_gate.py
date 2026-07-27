"""Task 1 scaffolding smoke: the safety chain itself comes up.

Verb coverage lives in the other modules; this exercises the fixture chain
(env gate → scratch redirect → session lease → TCP probe → upfront backup →
state capture) end to end so a broken safety net fails loudly on its own.
"""

from __future__ import annotations

import os


def test_env_redirect_is_scratch(scratch):
    for var in ("HELIXGEN_SETLISTS", "HELIXGEN_IRS", "HELIXGEN_IRHASH_CACHE", "HELIXGEN_PREFS"):
        assert os.environ[var].startswith(str(scratch)), (var, os.environ[var])
    assert os.environ["HELIXGEN_DEVICE_BACKUPS"] == str(scratch / "backups")


def test_safety_chain_up(helix, device_backup, scratch):
    assert (device_backup / "manifest.json").exists()
    assert device_backup == scratch / "backups"

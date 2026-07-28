"""Task 3: mutating verbs of ``RealDevicePort`` on hardware, ``HGTEST``-scoped.

Every artifact is ``HGTEST``-prefixed, torn down in ``finally`` blocks even on
failure, and the session ``device_state_guard`` backstops any leak. Assertions
cover ``OpResult.ok`` AND the exact message the TUI footer shows — a verb that
fails soft with ``ok=False`` (or lies with ``ok=True``) is exactly the silent
breakage this suite exists to catch.

Scoping notes (see also the conftest docstring's excluded-verbs section):

* ``sync_all`` runs with ``gc=False`` only. The GC phase would delete device
  pool presets the (scratch) manifest doesn't reference — i.e. every real pool
  preset. The session state guard WOULD see it (``device list --json``
  defaults to ``--setlist user``, which is the pool), but only after the fact,
  and no TUI surface passes ``gc=True`` anyway. Deliberately excluded, same
  reason helixgen-core's live suite excludes ``sync --gc``.
* ``prune_irs`` executes a real deletion, so it is gated on the engine's own
  dry-run plan: the test skips unless the only orphan the prune would delete
  is its own ``HGTEST`` IR and there are no verification warnings.
* ``restore`` is write-excluded; only its unsupported path is asserted here
  (the plan path is covered in test_read_verbs).
"""

from __future__ import annotations

import json
import random
import re
import struct
import time
import wave
from pathlib import Path

import pytest

from helixgen_tui.core.models import OpResult

# The ONE definition — the conftest teardown sweeper refuses to touch anything
# without this prefix, so a second copy here could silently drift out of its
# reach and strand artifacts on real hardware. (pytest puts this directory on
# sys.path, so the sibling conftest imports by name.)
from conftest import HGTEST

SETLIST = f"{HGTEST}-TUI-SYNC"
TONE_A = f"{HGTEST} TUI Sync A"
TONE_B = f"{HGTEST} TUI Sync B"

CID_RE = re.compile(r"as cid (\d+)")
REGISTRY_WAIT_S = 20.0


def _assert_op(res, ok: bool, message: str) -> None:
    assert isinstance(res, OpResult)
    assert res.message == message
    assert res.ok is ok, res.message


# --------------------------------------------------------------------------
# shared HGTEST artifact helpers (modeled on helixgen-core tests/live)
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def amp_blocks(cli) -> list[dict]:
    code, out, err = cli("list-blocks", "--json", "--category", "amp")
    assert code == 0, err or out
    blocks = json.loads(out)
    if not blocks:
        pytest.skip("library has no amp blocks")
    return blocks


def _generate_hsp(cli, scratch: Path, name: str, block: str) -> Path:
    """An HGTEST one-amp .hsp; ``generate`` registers it into the SCRATCH
    manifest (never the real one — _live_env redirects it)."""
    assert name.startswith(HGTEST)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name)
    recipe = scratch / "work" / f"{slug}.recipe.json"
    recipe.write_text(
        json.dumps(
            {
                "name": name,
                "author": "hgtest",
                "paths": [{"blocks": [{"block": block}]}],
            }
        )
    )
    out_path = scratch / "work" / f"{slug}.hsp"
    code, out, err = cli("generate", recipe, "-o", out_path)
    assert code == 0, f"generate failed: {err or out}"
    assert out_path.exists()
    return out_path


def _device_setlists(helix) -> list[dict]:
    code, out, err = helix("device", "setlists", "--json")
    assert code == 0, err or out
    return json.loads(out)


def _device_ir_rows(helix) -> dict[str, dict]:
    code, out, err = helix("device", "list-irs", "--json")
    assert code == 0, err or out
    return {m["hash"]: m for m in json.loads(out)}


def _wait_ir_registered(helix, irhash: str) -> bool:
    deadline = time.time() + REGISTRY_WAIT_S
    while time.time() < deadline:
        if irhash in _device_ir_rows(helix):
            return True
        time.sleep(2)
    return False


def _teardown_device_ir(helix, irhash: str, registered: bool) -> None:
    """Core's device_ir teardown contract: never assert, only ever addresses
    the hash THIS test pushed; a never-registered push may have wedged a file
    (invisible to the state guard) — ``--force-wedge`` is the CLI's remedy."""
    code, out, err = helix("device", "list-irs", "--json")
    try:
        listed = code == 0 and irhash in {m["hash"] for m in json.loads(out)}
    except (ValueError, KeyError, TypeError):
        listed = False
    if listed:
        code, out, err = helix("device", "delete-ir", irhash, "--yes")
    elif not registered:
        code, out, err = helix("device", "delete-ir", irhash, "--force-wedge", "--yes")
    else:
        return
    if code != 0:
        print(
            f"\n[tests/live] WARNING: IR teardown could not delete "
            f"{irhash}: {(err or out).strip()}"
        )


def _write_test_wav(path: Path, seed: int, frames: int = 2048) -> Path:
    """Deterministic 48 kHz mono 16-bit impulse-ish WAV (stdlib only)."""
    rnd = random.Random(seed)  # seeded Random is deterministic by contract
    samples = [32000]
    for i in range(1, frames):
        decay = 1.0 - i / frames
        samples.append(int(rnd.randrange(-32768, 32768) * 0.25 * decay))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(struct.pack(f"<{frames}h", *samples))
    return path


def _register_hgtest_wav(cli, scratch: Path, stem: str, seed: int) -> tuple[Path, str]:
    """Write + register (in the SCRATCH mapping, in place) an HGTEST IR wav;
    returns (path, irhash). Skips if libsndfile can't hash on this machine."""
    assert stem.startswith(HGTEST)
    wav = _write_test_wav(scratch / "work" / f"{stem}.wav", seed=seed)
    code, out, err = cli("irhash", wav, "--json")
    if code != 0:
        pytest.skip(f"cannot hash WAVs on this machine (libsndfile?): {err or out}")
    rec = next(r for r in json.loads(out) if r["basename"] == wav.name)
    code, out, err = cli("register-irs", wav, "--no-copy")
    assert code == 0, f"register-irs failed: {err or out}"
    return wav, rec["hash"]


# --------------------------------------------------------------------------
# sync verbs — a full HGTEST setlist lifecycle through the PORT
# --------------------------------------------------------------------------


def test_sync_lifecycle_via_port(real_port, helix, cli, scratch, amp_blocks):
    """setlist create + 2 tones → port.sync_setlist (installs, flips synced)
    → port.sync_tone (idempotent skip) → port.sync_all(gc=False) (managed-set
    mirror: untracked device setlists untouched) → unsync + cleanup sync
    (pool presets provably deleted) → setlist delete."""
    hsp_a = _generate_hsp(cli, scratch, TONE_A, amp_blocks[0]["display_name"])
    hsp_b = _generate_hsp(cli, scratch, TONE_B, amp_blocks[0]["display_name"])
    untracked_before = [
        (m.get("cid_"), m.get("name"), m.get("posi"))
        for m in _device_setlists(helix)
        if not (m.get("name") or "").startswith(HGTEST)
    ]
    try:
        code, out, err = helix("device", "setlist", "create", SETLIST)
        assert code == 0, err or out
        for hsp in (hsp_a, hsp_b):
            code, out, err = helix("device", "setlist", "add", SETLIST, hsp)
            assert code == 0, err or out

        # first targeted sync: installs both tones, flips the setlist synced
        res = real_port.sync_setlist(SETLIST, gc=False)
        _assert_op(
            res,
            True,
            f"synced setlist {SETLIST!r} — 2 installed, 0 updated, 0 skipped, 0 failed",
        )

        # sync_tone rides the now-synced setlist; unchanged tones skip
        res = real_port.sync_tone(TONE_A)
        _assert_op(
            res,
            True,
            f"synced {TONE_A!r} — 0 installed, 0 updated, 2 skipped, 0 failed",
        )

        # sync_all is a managed-set mirror: only synced manifest setlists
        # (here: the HGTEST one) are touched — confirm the untracked device
        # setlist CONTAINERS are unchanged (their entries aren't listed by
        # `device setlists --json`; the session state guard's pool capture is
        # what would catch a reference written into one)
        res = real_port.sync_all(gc=False)
        _assert_op(
            res,
            True,
            "synced all setlists — 0 installed, 0 updated, 2 skipped, 0 failed",
        )
        untracked_after = [
            (m.get("cid_"), m.get("name"), m.get("posi"))
            for m in _device_setlists(helix)
            if not (m.get("name") or "").startswith(HGTEST)
        ]
        assert untracked_after == untracked_before

        # unsync both → the cleanup sync's own report must show the HGTEST
        # pool presets DELETED (the session guard would catch a leak at
        # teardown; this pins it to THIS test instead)
        for tone in (TONE_A, TONE_B):
            code, out, err = helix("device", "unsync", tone)
            assert code == 0, err or out
        code, out, err = helix("device", "sync", SETLIST, "--json", timeout=600)
        assert code == 0, err or out
        report = json.loads(out)
        assert not report.get("errors"), report["errors"]
        assert {TONE_A, TONE_B} <= set(report["pool"].get("deleted", [])), report

        code, out, err = helix("device", "setlist", "delete", SETLIST, "--yes")
        assert code == 0, err or out
    finally:
        # belt-and-braces on failure: unsync, cleanup-sync if the setlist
        # survived, drop it. Report (never assert) problems here — the session
        # state guard is what fails the run on a leak.
        for tone in (TONE_A, TONE_B):
            helix("device", "unsync", tone)
        still_there = any(m.get("name") == SETLIST for m in _device_setlists(helix))
        if still_there:
            code, out, err = helix("device", "sync", SETLIST, "--json", timeout=600)
            if code != 0:
                print(
                    f"\n[tests/live] WARNING: cleanup sync of {SETLIST!r} failed — "
                    f"HGTEST pool presets may remain: {(err or out).strip()}"
                )
            code, out, err = helix("device", "setlist", "delete", SETLIST, "--yes")
            if code != 0:
                print(
                    f"\n[tests/live] WARNING: could not delete setlist "
                    f"{SETLIST!r}: {(err or out).strip()}"
                )


def test_sync_tone_outside_synced_setlists_fails_soft(real_port, helix):
    """A tone in no synced setlist fails soft with the footer's guidance —
    and never reaches the device (local manifest check only)."""
    tone = f"{HGTEST} not-in-any-setlist"
    res = real_port.sync_tone(tone)
    _assert_op(
        res,
        False,
        f"{tone!r} is in no synced setlist — sync a setlist from the Setlists screen",
    )


# --------------------------------------------------------------------------
# make_active — changes the player's ACTIVE tone by design
# --------------------------------------------------------------------------


def _active(helix) -> dict:
    code, out, err = helix("device", "active", "--json")
    assert code == 0, err or out
    return json.loads(out)


def test_make_active_roundtrip(real_port, helix, cli, scratch, amp_blocks):
    """Install an HGTEST preset in a free user slot, make it active through
    the port, then restore the player's original selection BEFORE deleting
    the HGTEST preset (never leave the edit buffer on a deleted tone)."""
    before = _active(helix)
    assert isinstance(before.get("cid"), int), before

    tone = f"{HGTEST} TUI Active"
    hsp = _generate_hsp(cli, scratch, tone, amp_blocks[0]["display_name"])
    code, out, err = helix("device", "list", "--json")
    assert code == 0, err or out
    occupied = {m.get("posi") for m in json.loads(out)}
    free = [p for p in range(127, -1, -1) if p not in occupied]
    if not free:
        pytest.skip("no empty user slot for the make_active preset")

    code, out, err = helix("device", "install", hsp, tone, "--pos", free[0])
    assert code == 0, f"device install failed: {err or out}"
    m = CID_RE.search(out)
    assert m, f"no cid in install output: {out!r}"
    cid = int(m.group(1))
    try:
        res = real_port.make_active(tone)
        _assert_op(res, True, f"made {tone!r} active")
        assert _active(helix).get("name") == tone

        # unknown tone fails soft and leaves the selection alone
        missing = f"{HGTEST} no-such-tone"
        res = real_port.make_active(missing)
        _assert_op(res, False, f"{missing!r} is not on the device")
        assert _active(helix).get("name") == tone
    finally:
        # restore the player's selection FIRST, then drop the HGTEST preset
        code, out, err = helix("device", "load", before["cid"])
        if code != 0:
            print(
                f"\n[tests/live] WARNING: could not restore active preset "
                f"cid {before['cid']}: {(err or out).strip()}"
            )
        code, out, err = helix("device", "delete", cid, "--yes")
        if code != 0:
            print(
                f"\n[tests/live] WARNING: could not delete HGTEST preset "
                f"cid {cid}: {(err or out).strip()}"
            )
    assert _active(helix).get("cid") == before["cid"]


# --------------------------------------------------------------------------
# device IRs — push / rename / delete, then the gated prune
# --------------------------------------------------------------------------


def test_ir_push_rename_delete_roundtrip(real_port, helix, cli, scratch):
    stem = f"{HGTEST}-tui-ir"
    renamed = f"{HGTEST} TUI renamed IR"
    wav, irhash = _register_hgtest_wav(cli, scratch, stem, seed=7)
    registered = False
    try:
        # the screen sends IrVM.name — a stem — and push_ir resolves it
        # through the local mapping (hash / basename / stem)
        res = real_port.push_ir(stem)
        _assert_op(res, True, f"pushed IR {stem!r}")
        registered = _wait_ir_registered(helix, irhash)
        assert registered, (
            f"pushed IR never appeared in the device registry within "
            f"{REGISTRY_WAIT_S:.0f}s (the engine's push nudges the -11 "
            f"listing cache, so a missing entry is a real regression)"
        )

        res = real_port.rename_ir(irhash, renamed)
        _assert_op(res, True, f"renamed IR to {renamed!r}")
        assert _device_ir_rows(helix)[irhash]["name"] == renamed

        res = real_port.delete_ir(irhash)
        # NOT _assert_op: the message is deliberately conditional. The engine's
        # advisory SFTP half (``file_removed``) fails on any machine without a
        # usable hedit key, and the port appends "(registry entry removed;
        # backing file left on the device)" when it does — a partial success,
        # not a regression. The registry check below is the real assertion.
        assert isinstance(res, OpResult)
        assert res.ok is True, res.message
        assert res.message.startswith(f"deleted IR {irhash!r}"), res.message
        assert irhash not in _device_ir_rows(helix)
    finally:
        _teardown_device_ir(helix, irhash, registered)


def test_prune_irs_executes_only_against_hgtest_orphans(real_port, helix, cli, scratch):
    """``prune_irs`` deletes for real, so it is gated on the engine's own
    dry-run: unless the only orphan is this test's HGTEST IR (and there are
    no verification warnings), skip rather than touch the user's IRs."""
    stem = f"{HGTEST}-tui-prune-ir"
    wav, irhash = _register_hgtest_wav(cli, scratch, stem, seed=11)
    registered = False
    try:
        res = real_port.push_ir(stem)
        _assert_op(res, True, f"pushed IR {stem!r}")
        registered = _wait_ir_registered(helix, irhash)
        assert registered, "pushed IR never appeared in the device registry"

        code, out, err = helix("device", "ir-prune", "--json", timeout=300)
        assert code == 0, err or out
        plan = json.loads(out)
        foreign = [
            o
            for o in plan.get("orphans", [])
            if not (o.get("name") or "").startswith(HGTEST)
        ]
        if foreign or plan.get("warnings"):
            pytest.skip(
                "device has non-HGTEST prunable IRs (or verification "
                f"warnings) — not executing a real prune over them: "
                f"orphans={foreign} warnings={plan.get('warnings')}"
            )
        assert any(o.get("hash") == irhash for o in plan.get("orphans", [])), plan

        # the port's plan must name the orphan the engine reports (the plan
        # feeds the destructive ConfirmModal)
        planned = " ".join(real_port.plan_prune_irs().lines)
        name = next(o.get("name") for o in plan["orphans"] if o.get("hash") == irhash)
        assert name in planned, planned

        res = real_port.prune_irs()
        _assert_op(res, True, "pruned 1 unreferenced device IR(s)")
        assert irhash not in _device_ir_rows(helix)
    finally:
        _teardown_device_ir(helix, irhash, registered)


# --------------------------------------------------------------------------
# backup (writes to SCRATCH only) + verbs that must not touch the device
# --------------------------------------------------------------------------


def test_backup_via_port(real_port, helix, scratch):
    code, out, err = helix("device", "list", "--json")
    assert code == 0, err or out
    n = len(json.loads(out))
    # The upfront `device_backup` fixture already wrote one .sbe per preset
    # into this same dir under the same names, so a bare file COUNT would hold
    # whether or not the port wrote anything. Compare mtimes instead.
    backups = scratch / "backups"
    before = {p: p.stat().st_mtime_ns for p in backups.glob("*.sbe")}
    time.sleep(0.01)  # mtime_ns resolution guard on coarse filesystems
    res = real_port.backup()
    _assert_op(res, True, f"backed up {n} preset(s)")
    # $HELIXGEN_DEVICE_BACKUPS redirects the port's default backup dir
    after = {p: p.stat().st_mtime_ns for p in backups.glob("*.sbe")}
    assert len(after) >= n
    assert any(before.get(p) != m for p, m in after.items()), (
        "no .sbe under $HELIXGEN_DEVICE_BACKUPS was written or rewritten — "
        "the port's backup did not land in the scratch redirect"
    )


def test_delete_tone_is_unwired(real_port):
    tone = f"{HGTEST} any"
    res = real_port.delete_tone(tone)
    _assert_op(
        res,
        False,
        f"deleting {tone!r} from the device isn't wired to the TUI yet",
    )


def test_restore_is_write_excluded(real_port):
    res = real_port.restore("whatever.json")
    assert isinstance(res, OpResult)
    assert res.ok is False
    assert "restore" in res.message

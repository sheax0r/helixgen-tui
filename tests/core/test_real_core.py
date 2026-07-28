"""build_core() wiring: real library/setlists + the offline-first RealDevicePort.

Every test here forces the OFFLINE state (no device record, and the ambient
``$HELIXGEN_HELIX_IP`` is deleted so a dev machine pointed at the real Helix
can't leak a connection). The networked verbs are checked only for their
offline behavior and their signatures — never driven against hardware.
"""

from __future__ import annotations

import errno
import inspect
import os
from contextlib import contextmanager

import pytest

from helixgen_tui.core.models import DeviceStateVM, IrVM, MutationPlan, OpResult
from helixgen_tui.core.ports import Core, DevicePort, DeviceUnreachable
from helixgen_tui.core.real import RealDevicePort, build_core


@pytest.fixture
def offline(tmp_home, monkeypatch):
    """tmp_home with no discovered device and no HELIXGEN_HELIX_IP — resolve_ip
    raises immediately, so nothing can open a socket."""
    monkeypatch.delenv("HELIXGEN_HELIX_IP", raising=False)
    return tmp_home


def test_build_core_satisfies_core_protocol(offline):
    core = build_core()
    assert isinstance(core, Core)
    assert isinstance(core.device, RealDevicePort)
    assert isinstance(core.device, DevicePort)  # runtime_checkable: all verbs present


def test_real_device_port_matches_protocol_signatures():
    """Signature-level conformance (no calls): every DevicePort method exists on
    RealDevicePort with the same parameter names."""
    for name, proto_member in inspect.getmembers(DevicePort, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        impl = getattr(RealDevicePort, name, None)
        assert impl is not None, f"RealDevicePort missing {name}"
        proto_params = list(inspect.signature(proto_member).parameters)
        impl_params = list(inspect.signature(impl).parameters)
        assert impl_params == proto_params, f"{name}: {impl_params} != {proto_params}"


def test_list_local_irs_empty_home(offline):
    assert build_core().list_local_irs() == []


def test_probe_offline_raises_device_unreachable(offline):
    with pytest.raises(DeviceUnreachable):
        build_core().device.probe()


def test_make_active_offline_raises_device_unreachable(offline):
    # resolve_ip fails before any socket is opened.
    with pytest.raises(DeviceUnreachable):
        build_core().device.make_active("some-tone")


def test_sync_tone_not_in_any_setlist_is_soft_failure(offline):
    # Empty manifest -> the tone is in no setlist, so we refuse without a device.
    result = build_core().device.sync_tone("orphan-tone")
    assert result.ok is False
    assert "setlist" in result.message


def test_lock_status_offline_is_empty(offline):
    assert build_core().device.lock_status() == []


def test_restore_reports_cid_gap_without_device(offline):
    result = build_core().device.restore("backup.sbe")
    assert result.ok is False
    assert "cid" in result.message


def test_delete_tone_is_not_wired_yet(offline):
    result = build_core().device.delete_tone("t")
    assert result.ok is False


def test_plans_are_offline_and_well_formed(offline):
    device = build_core().device
    assert isinstance(device.plan_sync_all(gc=False), MutationPlan)
    assert isinstance(device.plan_delete_tone("t"), MutationPlan)
    assert isinstance(device.plan_restore("f"), MutationPlan)
    assert isinstance(device.plan_delete_ir("ir"), MutationPlan)


def test_device_state_vm_and_irvm_types_are_importable():
    # Guards the module's typed surface without touching a device.
    assert DeviceStateVM and IrVM and OpResult


# --- Fix 1: push_ir resolves a registered IR (stem/basename/hash) ----------


def _register_ir(tmp_path, stem="V30 Cab", irhash="deadbeefcafef00ddeadbeefcafef00d"):
    """Seed one registered IR through core's own IrMapping writer. Returns hash."""
    from helixgen.ir import IrMapping

    wav = tmp_path / f"{stem}.wav"
    wav.write_bytes(b"RIFF0000WAVEfmt ")  # register only checks is_file()
    mapping = IrMapping.load()
    mapping.register(irhash, wav)
    mapping.save()
    return irhash


def test_push_ir_resolves_registered_ir_by_stem(tmp_home, tmp_path, monkeypatch):
    """The screen pushes IrVM.name (a *stem*, no extension). push_ir must resolve
    it to the registered IR's hash and hand THAT to the upload — the old
    basename compare (against '<stem>.wav') never matched, so every push failed.
    Only the final network upload is monkeypatched; nothing opens a socket."""
    import helixgen.device.ir_upload as ir_upload

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")  # pure env read; no socket
    irhash = _register_ir(tmp_path)

    captured: dict = {}

    def fake_upload(ip, hashes):
        captured["ip"] = ip
        captured["hashes"] = list(hashes)
        return [{"ok": True, "outcome": "imported"}]

    monkeypatch.setattr(ir_upload, "upload_missing_irs", fake_upload)

    result = build_core().device.push_ir("V30 Cab")  # the stem, as the screen sends
    assert result.ok is True
    assert captured["hashes"] == [irhash]


def test_push_ir_by_irhash_reports_the_registered_stem(tmp_home, tmp_path, monkeypatch):
    """The IRs screen pushes ``ir.irhash or ir.name`` — i.e. a raw HASH
    whenever one is known, so duplicate display names stay unambiguous. That
    branch must resolve to itself AND still label the footer with the
    registered file's stem, not the 32-char hash."""
    import helixgen.device.ir_upload as ir_upload

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    irhash = _register_ir(tmp_path)

    captured: dict = {}

    def fake_upload(ip, hashes):
        captured["hashes"] = list(hashes)
        return [{"ok": True, "outcome": "imported"}]

    monkeypatch.setattr(ir_upload, "upload_missing_irs", fake_upload)

    result = build_core().device.push_ir(irhash)  # the hash, as the screen sends
    assert result.ok is True
    assert captured["hashes"] == [irhash]
    assert result.message == "pushed IR 'V30 Cab'", result.message


def test_push_ir_engine_soft_failure_flips_ok_false(tmp_home, tmp_path, monkeypatch):
    """The engine's upload result carries per-hash ``ok`` (True only for
    outcomes "already"/"imported"). A soft failure like "upload_failed" or
    "not_yet_registered" has no "upload_error" outcome but is NOT a success —
    push_ir must report ok=False and surface the engine's note, not claim
    the push worked (found live 2026-07-27: every soft failure reported ok)."""
    import helixgen.device.ir_upload as ir_upload

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    _register_ir(tmp_path)

    for outcome, note in [
        ("upload_failed", "failed to upload V30 Cab.wav"),
        ("not_yet_registered", "uploaded but not yet registered — retry shortly"),
        ("hash_mismatch", "registered under a different hash — cab won't resolve"),
    ]:
        monkeypatch.setattr(
            ir_upload,
            "upload_missing_irs",
            lambda ip, hashes, _o=outcome, _n=note: [
                {"ok": False, "outcome": _o, "note": _n}
            ],
        )
        result = build_core().device.push_ir("V30 Cab")
        assert result.ok is False, f"outcome {outcome!r} must not report success"
        assert note in result.message


def test_push_ir_unknown_ir_is_soft_failure(tmp_home, monkeypatch):
    """An IR name that matches no registered entry fails soft (ok=False), and
    never reaches the upload call."""
    import helixgen.device.ir_upload as ir_upload

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(ip, hashes):  # pragma: no cover - must never run
        raise AssertionError("upload should not be reached for an unknown IR")

    monkeypatch.setattr(ir_upload, "upload_missing_irs", boom)

    result = build_core().device.push_ir("no-such-ir")
    assert result.ok is False
    assert "no-such-ir" in result.message


# --- Fix 2: sync summarizes the report's bucket counts ---------------------


def _canned_report(
    *, installed=(), updated=(), skipped=(), errors=(), deleted=(), delete_skipped=()
):
    return {
        "ok": not errors,
        "setlists": [],
        "pool": {
            "installed": list(installed),
            "updated": list(updated),
            "skipped": list(skipped),
            "deleted": list(deleted),
            "delete_skipped": list(delete_skipped),
        },
        "references": {},
        "gc": {"deleted": []},
        "irs": [],
        "errors": list(errors),
    }


def test_sync_setlist_summarizes_report_counts(tmp_home, monkeypatch):
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    report = _canned_report(installed=["a", "b"], updated=["c"])
    monkeypatch.setattr(setlist_sync, "sync_setlists", lambda *a, **k: report)

    result = build_core().device.sync_setlist("Gig 1", gc=False)
    assert result.ok is True
    assert "2 installed" in result.message
    assert "1 updated" in result.message
    assert "0 failed" in result.message
    assert "Gig 1" in result.message


def test_sync_summary_is_pinned_whole_not_by_substring(tmp_home, monkeypatch):
    """Every other offline sync test uses ``in`` checks, so a bucket added to
    (or reordered in) the summary stays green here while the live suite — which
    compares with ``==`` — only fails on hardware, months later. Pin the whole
    string so the drift is caught by ``uv run pytest``."""
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    monkeypatch.setattr(
        setlist_sync, "sync_setlists", lambda *a, **k: _canned_report(installed=["a", "b"])
    )

    result = build_core().device.sync_setlist("Gig 1", gc=False)
    assert result.message == (
        "synced setlist 'Gig 1' — 2 installed, 0 updated, 0 deleted, 0 skipped, 0 failed"
    )


def test_sync_all_failures_flip_ok_false_and_are_counted(tmp_home, monkeypatch):
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    report = _canned_report(skipped=["x"], errors=["tone 'x': install failed"])
    monkeypatch.setattr(setlist_sync, "sync_setlists", lambda *a, **k: report)

    result = build_core().device.sync_all(gc=False)
    assert result.ok is False
    assert "1 failed" in result.message
    assert "1 skipped" in result.message


def test_sync_reports_the_mirror_deletes_it_performed(tmp_home, monkeypatch):
    """``pool.deleted`` is the ordinary "unsync a tone, then sync" outcome.
    Dropping it reported "0 installed, 0 updated, 0 skipped, 0 failed" over a
    sync that removed presets from the device — indistinguishable from a
    no-op."""
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    report = _canned_report(deleted=["Old Tone", "Older Tone"])
    monkeypatch.setattr(setlist_sync, "sync_setlists", lambda *a, **k: report)

    result = build_core().device.sync_all(gc=False)
    assert result.ok is True
    assert "2 deleted" in result.message


def test_sync_fails_when_the_engine_refuses_a_mirror_delete(tmp_home, monkeypatch):
    """``pool.delete_skipped`` is the engine REFUSING a delete (a live setlist
    still references the preset) and it is never appended to ``errors`` — so
    folding only ``errors`` reported ok=True while the tone stayed on the
    device. Same class as the IR verbs' "success over a refusal"."""
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    report = _canned_report(delete_skipped=["Still Referenced"])
    monkeypatch.setattr(setlist_sync, "sync_setlists", lambda *a, **k: report)

    result = build_core().device.sync_all(gc=False)
    assert result.ok is False, report
    assert "Still Referenced" in result.message


def test_sync_failures_name_what_failed_not_just_how_many(tmp_home, monkeypatch):
    """The footer is the only diagnostic surface in the app. Folding `errors`
    to a bare count destroyed the engine's per-tone remediation text at exactly
    the point the fail-soft rule exists to preserve it — including an IR-upload
    soft failure arriving via sync instead of `p`."""
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    report = _canned_report(errors=["tone 'Riff': slot 3B occupied", "tone 'Lead': timeout"])
    monkeypatch.setattr(setlist_sync, "sync_setlists", lambda *a, **k: report)

    result = build_core().device.sync_all(gc=False)
    assert result.ok is False
    assert "2 failed" in result.message
    assert "slot 3B occupied" in result.message


def test_sync_report_keys_the_port_reads_are_the_engine_s():
    """Every ``pool`` bucket the fold reads is pinned to the installed engine's
    SOURCE, not its docstring — a renamed bucket must break the test that folds
    it, and `deleted`/`delete_skipped` are the two whose absence silently
    reported a no-op (resp. a success) over a real device mutation."""
    from helixgen.device import setlist_sync

    source = inspect.getsource(setlist_sync.sync_setlists)
    missing = [
        key
        for key in ("installed", "updated", "skipped", "deleted", "delete_skipped")
        if f'"{key}"' not in source and f"'{key}'" not in source
    ]
    assert missing == [], missing
    # ...and the refusal really is kept out of `errors`, which is why the fold
    # cannot treat `errors` alone as "did anything fail".
    assert 'result["pool"]["delete_skipped"].append' in source


# --- Fix 3: sync_tone only mirrors setlists already opted into syncing ------


def _seed_tone_in_setlist(setlist_name, *, synced, stem="riff-tone", preset="Riff Tone"):
    """Register a .hsp tone into a (draft or synced) setlist via core APIs.
    Returns the manifest tone name."""
    from helixgen import home, hsp
    from helixgen.device.manifest import SetlistManifest

    tones_dir = home.tones_dir()
    tones_dir.mkdir(parents=True, exist_ok=True)
    hsp_path = tones_dir / f"{stem}.hsp"
    hsp.write_hsp(hsp_path, {"meta": {"name": preset}, "preset": {}})
    manifest = SetlistManifest.load()
    name = manifest.register_tone(hsp_path)
    manifest.create_setlist(setlist_name)
    manifest.add_to_setlist(setlist_name, name)
    manifest.set_setlist_synced(setlist_name, synced)
    manifest.save()
    return name


def test_sync_tone_in_only_a_draft_setlist_refuses(tmp_home, monkeypatch):
    """A tone that lives only in a draft (non-synced) setlist must NOT silently
    flip that setlist to mirror-enabled — sync_tone refuses instead."""
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("sync must not run for a draft-only tone")

    monkeypatch.setattr(setlist_sync, "sync_setlists", boom)
    name = _seed_tone_in_setlist("Draft", synced=False)

    result = build_core().device.sync_tone(name)
    assert result.ok is False
    assert "no synced setlist" in result.message


def test_sync_tone_in_synced_setlist_syncs_only_that_setlist(tmp_home, monkeypatch):
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    captured: dict = {}

    def fake_sync(manifest, *, ip=None, port=None, setlists=None, gc=False, **k):
        captured["setlists"] = setlists
        return _canned_report(installed=[setlists[0]] if setlists else [])

    monkeypatch.setattr(setlist_sync, "sync_setlists", fake_sync)
    name = _seed_tone_in_setlist("Gig 1", synced=True)

    result = build_core().device.sync_tone(name)
    assert result.ok is True
    assert captured["setlists"] == ["Gig 1"]


# --- Fix 4: the IR prune/delete verbs read the engine's real report shape ---


def _prune_report(*, orphans=(), deleted=(), errors=(), warnings=()):
    """``maintenance.ir_prune``'s documented return shape."""
    return {
        "ok": not errors,
        "dry_run": not deleted,
        "device_irs": len(orphans),
        "referenced": [],
        "protected": [],
        "orphans": list(orphans),
        "deleted": list(deleted),
        "warnings": list(warnings),
        "errors": list(errors),
    }


def test_plan_prune_irs_lists_the_orphans_the_engine_reports(tmp_home, monkeypatch):
    """The plan feeds a destructive ConfirmModal. It used to read "prunable"/
    "prune" — keys the engine has never emitted — so it always claimed there
    was nothing to prune while the confirm deleted for real."""
    from helixgen.device import maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    report = _prune_report(orphans=[{"name": "Old Cab", "hash": "abc"}])
    monkeypatch.setattr(maintenance, "ir_prune", lambda **k: report)

    plan = build_core().device.plan_prune_irs()
    assert "Old Cab" in " ".join(plan.lines)
    assert "no unreferenced" not in " ".join(plan.lines)


def test_plan_prune_irs_renders_the_empty_case(tmp_home, monkeypatch):
    from helixgen.device import maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    monkeypatch.setattr(maintenance, "ir_prune", lambda **k: _prune_report())
    assert "(no unreferenced device IRs to prune)" in build_core().device.plan_prune_irs().lines


def test_plan_prune_irs_refuses_to_plan_over_verification_warnings(tmp_home, monkeypatch):
    """``ir_prune(execute=True)`` RAISES over these warnings unless
    ``ignore_warnings`` is passed, and this port never passes it — so a plan
    that renders them as text opens a ConfirmModal whose confirm can only ever
    fail. Refuse to plan instead."""
    from helixgen.device import maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    monkeypatch.setattr(
        maintenance,
        "ir_prune",
        lambda **k: _prune_report(
            orphans=[{"name": "Old Cab", "hash": "abc"}], warnings=["tone 'x' unreadable"]
        ),
    )
    with pytest.raises(RuntimeError, match="tone 'x' unreadable"):
        build_core().device.plan_prune_irs()


def test_plan_prune_irs_raises_a_planning_failure(tmp_home, monkeypatch):
    """The plan feeds a destructive ConfirmModal: a planning abort (e.g. the
    engine's pool cross-check) must propagate so DeviceService.query reports it
    and the modal never opens — swallowing it into plan text offered a
    confirmable prune with no preview of what the confirm would delete."""
    from helixgen.device import HelixError, maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(**k):
        raise HelixError("device listings changed between scans")

    monkeypatch.setattr(maintenance, "ir_prune", boom)
    with pytest.raises(HelixError, match="device listings changed between scans"):
        build_core().device.plan_prune_irs()


def test_plan_prune_irs_offline_raises_unreachable(offline):
    with pytest.raises(DeviceUnreachable):
        build_core().device.plan_prune_irs()


def test_plan_prune_irs_connect_failure_flips_the_app_offline(tmp_home, monkeypatch):
    """The plan runs FIRST in the prune flow, and ``ir_prune`` connects itself —
    so a device that dropped off the LAN raises HelixError here too. Letting the
    raw HelixError out makes DeviceService report a generic error and leave the
    header claiming "connected" over an unreachable device: the same asymmetry
    ``prune_irs`` is already guarded against, on the half that runs first."""
    from helixgen.device import HelixError, maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(**k):
        raise HelixError("no Helix Stadium answered at 10.255.255.1:2002 (timed out)")

    monkeypatch.setattr(maintenance, "ir_prune", boom)
    with pytest.raises(DeviceUnreachable):
        build_core().device.plan_prune_irs()


def test_prune_irs_reports_the_backing_files_it_left_behind(tmp_home, monkeypatch):
    """``ir_prune`` stamps ``file_removed`` on every deleted entry, same as
    ``delete_device_ir``. Counting only ``len(deleted)`` reported a clean prune
    over registry rows removed with their .wav files still on the device — the
    wedged state --force-wedge exists to clean, hidden on the destructive
    sibling of the verb already fixed for it."""
    from helixgen.device import maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    monkeypatch.setattr(
        maintenance,
        "ir_prune",
        lambda **k: _prune_report(
            deleted=[
                {"name": "Old Cab", "file_removed": True},
                {"name": "Older Cab", "file_removed": False},
            ]
        ),
    )
    result = build_core().device.prune_irs()
    assert result.ok is True
    assert result.message == (
        "pruned 2 unreferenced device IR(s) (1 backing file(s) left on the device)"
    )


def test_prune_irs_clean_run_says_nothing_about_backing_files(tmp_home, monkeypatch):
    from helixgen.device import maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    monkeypatch.setattr(
        maintenance,
        "ir_prune",
        lambda **k: _prune_report(deleted=[{"name": "Old Cab", "file_removed": True}]),
    )
    result = build_core().device.prune_irs()
    assert result.ok is True
    assert result.message == "pruned 1 unreferenced device IR(s)"


@pytest.mark.parametrize(
    "message",
    [
        # _verify_pool_covers_references, both of its raises
        "setlist 'Rock' has a stale (dangling) reference to cid 12, whose pool "
        "preset no longer exists — a leftover from a deleted preset. Remove it "
        "before pruning: re-sync the setlist (helixgen device sync 'Rock')",
        "pool listing looks incomplete: setlist 'Rock' references cid 12 which "
        "the pool listing doesn't contain; aborting — retry",
        # list_presets/list_irs strict= on a silent-empty or partial reply
        "empty reply to /GetContainerContents; refusing to read it as 'no presets'",
    ],
)
def test_prune_irs_healthy_device_aborts_are_not_reported_as_offline(
    tmp_home, monkeypatch, message
):
    """``_scan`` aborts on a REACHABLE device in more ways than the confirm
    re-scan disagreeing: the pool cross-check has two of its own, and strict
    listings raise on a truncated reply. Matching one abort's wording as the
    allowlist re-raises all the others into ``_op``, which reports a healthy
    device as "device offline" and throws away the engine's remediation text."""
    from helixgen.device import HelixError, maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(**k):
        raise HelixError(message)

    monkeypatch.setattr(maintenance, "ir_prune", boom)
    result = build_core().device.prune_irs()
    assert result.ok is False
    assert message in result.message


def test_prune_irs_counts_deletions_and_fails_on_engine_errors(tmp_home, monkeypatch):
    """``ir_prune`` accumulates per-IR refusals in ``errors`` and sets ok=False
    WITHOUT raising — a discarded report reported success over a failed prune."""
    from helixgen.device import maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    monkeypatch.setattr(
        maintenance,
        "ir_prune",
        # the engine stamps ``file_removed`` on every deleted entry; True is the
        # clean case (see the wedged-file tests below)
        lambda **k: _prune_report(deleted=[{"name": "Old Cab", "file_removed": True}]),
    )
    result = build_core().device.prune_irs()
    assert result.ok is True
    assert "pruned 1 unreferenced device IR(s)" == result.message

    monkeypatch.setattr(
        maintenance,
        "ir_prune",
        lambda **k: _prune_report(errors=["device refused to delete IR 'Old Cab'"]),
    )
    result = build_core().device.prune_irs()
    assert result.ok is False
    assert "device refused to delete IR 'Old Cab'" in result.message


def test_prune_irs_abort_is_not_reported_as_an_offline_device(tmp_home, monkeypatch):
    """``ir_prune``'s likeliest failure is an abort on a HEALTHY device (the
    re-scan disagreeing, nothing deleted). ``_op`` maps every HelixError to
    DeviceUnreachable, which would flip the whole app offline and say so."""
    from helixgen.device import HelixError, maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(**k):
        raise HelixError("device listings changed between the plan scan and the confirm scan")

    monkeypatch.setattr(maintenance, "ir_prune", boom)
    result = build_core().device.prune_irs()
    assert result.ok is False
    assert "device listings changed" in result.message


def test_prune_irs_connect_failure_still_flips_the_app_offline(tmp_home, monkeypatch):
    """The abort catch above must not swallow ir_prune's OWN connect failure —
    a device that dropped off the LAN raises HelixError too, and reporting that
    as a soft "prune aborted" leaves the app claiming it is still connected."""
    from helixgen.device import HelixError, maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(**k):
        raise HelixError("no Helix Stadium answered at 10.255.255.1:2002")

    monkeypatch.setattr(maintenance, "ir_prune", boom)
    with pytest.raises(DeviceUnreachable):
        build_core().device.prune_irs()


def test_delete_ir_reports_the_engine_refusal(tmp_home, monkeypatch):
    """``delete_device_ir`` returns ``ok=False`` (no raise) when the device
    refuses the removal; the port used to hardcode ok=True."""
    from helixgen.device import maintenance
    from helixgen_tui.core import real

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    @contextmanager
    def fake_session(self, ip):
        yield object()

    monkeypatch.setattr(real.RealDevicePort, "_session", fake_session)
    monkeypatch.setattr(
        maintenance,
        "delete_device_ir",
        lambda client, name, ip=None: {"ok": False, "name": name, "file_removed": False},
    )
    result = build_core().device.delete_ir("Old Cab")
    assert result.ok is False
    assert "Old Cab" in result.message

    monkeypatch.setattr(
        maintenance,
        "delete_device_ir",
        lambda client, name, ip=None: {"ok": True, "name": name, "file_removed": True},
    )
    result = build_core().device.delete_ir("Old Cab")
    assert result.ok is True
    assert result.message == "deleted IR 'Old Cab'"

    # registry delete succeeded, SFTP file removal did not: that is the wedged
    # state the engine needs --force-wedge to clean, not a clean delete
    monkeypatch.setattr(
        maintenance,
        "delete_device_ir",
        lambda client, name, ip=None: {"ok": True, "name": name, "file_removed": False},
    )
    result = build_core().device.delete_ir("Old Cab")
    assert result.ok is True
    assert "backing file left on the device" in result.message


# --- Fix 5: connect-class vs healthy-device-abort classification -------------


def test_connect_failure_markers_still_exist_in_the_installed_engine():
    """``_CONNECT_FAILURES`` is a hardcoded copy of the engine's connect-class
    messages. Pin it to the installed ``HelixClient``: if helixgen rewords one,
    every real connect/drop stops flipping the app offline and the header keeps
    claiming "connected" over a device that is gone — silently, because a test
    raising its own copy of the string would still pass."""
    from helixgen.device.client import HelixClient

    from helixgen_tui.core.real import _CONNECT_FAILURES

    source = inspect.getsource(HelixClient)
    assert [m for m in _CONNECT_FAILURES if m not in source] == []


@pytest.mark.parametrize(
    "verb, keys",
    [
        # plan_prune_irs/prune_irs read orphans+warnings and deleted+errors,
        # plus the per-entry SFTP half prune_irs folds
        ("ir_prune", ("orphans", "deleted", "warnings", "errors", "file_removed")),
        # delete_ir folds both halves of the report
        ("delete_device_ir", ("ok", "file_removed")),
    ],
)
def test_maintenance_report_keys_the_port_reads_are_the_engine_s(verb, keys):
    """The bug this branch exists to fix was reading ``prunable``/``prune``,
    keys ``ir_prune`` never emitted — so every folded key gets pinned to the
    installed engine's SOURCE. Pinning the docstring instead (what this test
    used to do) is uncorrelated with the defect: it passes while the engine
    documents keys it no longer emits, and fails when the engine merely rewords
    its prose."""
    from helixgen.device import maintenance

    source = inspect.getsource(getattr(maintenance, verb))
    assert [k for k in keys if f'"{k}"' not in source and f"'{k}'" not in source] == []


def test_upload_missing_irs_report_keys_push_ir_reads_are_the_engine_s():
    """``push_ir`` folds the engine's per-hash ``ok``/``note``; a rename there
    silently reinstates the "reported success over a refusal" class."""
    from helixgen.device import ir_upload

    source = inspect.getsource(ir_upload.upload_missing_irs)
    assert [k for k in ("ok", "note") if f'"{k}"' not in source and f"'{k}'" not in source] == []


def test_prune_irs_mid_operation_drop_flips_the_app_offline(tmp_home, monkeypatch):
    """``ir_prune`` runs two full strict scans, so the LIKELIEST connect-class
    failure is not the initial connect but a drop mid-RPC — a different engine
    message. Classifying only ``connect``'s message left that reported as a
    healthy-device abort with the header still showing "connected"."""
    from helixgen.device import HelixError, maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(**k):
        raise HelixError(
            "device connection lost after 3 reconnect attempts; if this "
            "persists, reboot the Helix"
        )

    monkeypatch.setattr(maintenance, "ir_prune", boom)
    with pytest.raises(DeviceUnreachable):
        build_core().device.prune_irs()
    with pytest.raises(DeviceUnreachable):
        build_core().device.plan_prune_irs()


def test_plan_prune_irs_oserror_flips_the_app_offline(tmp_home, monkeypatch):
    """Every sibling path maps a TRANSPORT OSError to offline; this half caught
    only HelixError, so a socket error reached DeviceService.query as a generic
    failure and left the header claiming "connected".

    Constructed with a real errno, not just "[Errno 65]" in the message:
    ``OSError("...")`` leaves ``exc.errno`` as None, so a test written that way
    passes against a classifier that inspects nothing."""
    from helixgen.device import maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(**k):
        raise OSError(errno.EHOSTUNREACH, "No route to host")

    monkeypatch.setattr(maintenance, "ir_prune", boom)
    with pytest.raises(DeviceUnreachable):
        build_core().device.plan_prune_irs()


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EACCES, errno.EROFS])
def test_local_disk_oserror_is_not_reported_as_an_offline_device(tmp_home, monkeypatch, code):
    """The device layer does LOCAL disk work under the same guards as its
    sockets — ``backup_setlist`` mkdirs and write_bytes into the backup dir. A
    blanket ``except OSError -> DeviceUnreachable`` reported a full disk / an
    unwritable backup dir as "device offline": the app blanked, the real cause
    (ENOSPC) was discarded, and the next 15s poll flipped the header back to
    connected."""
    from helixgen.device import backup as _backup

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    _connectable_client(monkeypatch, list_presets=lambda **k: [])

    def boom(client, *a, **k):
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(_backup, "backup_setlist", boom)
    result = build_core().device.backup()
    assert result.ok is False
    assert os.strerror(code) in result.message


def test_backup_lists_strictly_so_a_dropped_frame_is_not_an_empty_backup(tmp_home, monkeypatch):
    """`backup_setlist`'s own listing is the engine's NON-strict default, which
    reads a timeout or a truncated reply as an empty list — so a dropped frame
    wrote a manifest with zero entries and the port reported a green "backed up
    0 preset(s)" over the user's only restore point, right before a
    prune/sync/delete. The port must feed it a STRICT listing instead."""
    from helixgen.device import backup as _backup

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    _connectable_client(monkeypatch, list_presets=_strict_listing_that_drops)
    monkeypatch.setattr(_backup, "backup_setlist", _fail_if_called)

    result = build_core().device.backup()
    assert result.ok is False
    assert "refusing to treat it as empty" in result.message


def _strict_listing_that_drops(*, strict=False):
    from helixgen.device import HelixError

    if not strict:
        return []  # what the non-strict default does with a dropped reply
    raise HelixError(
        "no reply listing container -2 (timeout or connection drop); "
        "refusing to treat it as empty — retry, and reboot the Helix if it "
        "persists"
    )


def _fail_if_called(*a, **k):
    raise AssertionError("backup_setlist ran on a listing that never arrived")


def test_backup_setlist_still_takes_the_presets_the_port_injects():
    """Pinned to the engine's SOURCE: the `presets` kwarg the fix relies on,
    and the non-strict fallback that makes injecting it necessary. If the
    engine drops the kwarg, `backup()` silently reverts to the empty-backup
    bug rather than failing here."""
    from helixgen.device import backup as _backup

    assert "presets" in inspect.signature(_backup.backup_setlist).parameters
    source = inspect.getsource(_backup.backup_setlist)
    assert "if presets is None:" in source
    assert "client.list_presets(container)" in source  # i.e. strict=False


def test_transport_oserror_from_a_mutation_still_flips_the_app_offline(tmp_home, monkeypatch):
    """The other half of the errno split: the classifier must not be so narrow
    that a device genuinely off the LAN fails soft in the footer. EHOSTUNREACH
    arrives as a PLAIN OSError — it is not a ``ConnectionError`` subclass, so
    classifying by class instead of errno would miss it."""
    from helixgen.device import backup as _backup

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    _connectable_client(monkeypatch, list_presets=lambda **k: [])

    def boom(client, *a, **k):
        raise OSError(errno.EHOSTUNREACH, "No route to host")

    monkeypatch.setattr(_backup, "backup_setlist", boom)
    with pytest.raises(DeviceUnreachable):
        build_core().device.backup()


def _connectable_client(monkeypatch, **methods):
    """Replace ``HelixClient`` with a stub that connects. Keeps the port's REAL
    ``_session`` in the path — the mapping under test lives there. Extra
    keyword args attach client methods the verb under test calls."""
    import helixgen.device as device_pkg

    class _Client:
        def __init__(self, ip, port=None):
            for name, fn in methods.items():
                setattr(self, name, fn)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(device_pkg, "HelixClient", _Client)


def test_delete_ir_strict_listing_failure_is_not_reported_as_offline(tmp_home, monkeypatch):
    """``delete_device_ir`` resolves through ``resolve_device_ir_live``, whose
    ``-11`` listing is strict: a truncated/timed-out reply raises HelixError
    from a perfectly REACHABLE device. ``_session`` maps every HelixError to
    DeviceUnreachable, which flipped the whole app offline and threw the
    engine's remediation text away — the same asymmetry prune was fixed for."""
    from helixgen.device import HelixError, maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    _connectable_client(monkeypatch)

    def boom(client, name, ip=None):
        raise HelixError(
            "no reply listing container -11 (timeout or connection drop); "
            "refusing to treat it as empty — retry"
        )

    monkeypatch.setattr(maintenance, "delete_device_ir", boom)
    result = build_core().device.delete_ir("Old Cab")
    assert result.ok is False
    assert "refusing to treat it as empty" in result.message


def test_delete_ir_connect_failure_still_flips_the_app_offline(tmp_home, monkeypatch):
    """The other half of the split: a device that really is gone must still
    take the app offline rather than fail soft in the footer."""
    from helixgen.device import HelixError, maintenance

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    _connectable_client(monkeypatch)

    def boom(client, name, ip=None):
        raise HelixError("no Helix Stadium answered at 10.255.255.1:2002")

    monkeypatch.setattr(maintenance, "delete_device_ir", boom)
    with pytest.raises(DeviceUnreachable):
        build_core().device.delete_ir("Old Cab")


# --- Fix 6: strict listings, and reads that abort without going offline ------


@pytest.mark.parametrize(
    "verb, listing",
    [("_pool_cid_for", "list_presets"), ("list_device_irs", "list_irs")],
)
def test_port_listings_are_strict(verb, listing):
    """Both listings the port reads default to ``strict=False``, which reads a
    timeout or a truncated reply as an empty/partial list. ``_pool_cid_for``
    turns a missing row into the definitive claim "'X' is not on the device",
    and ``list_device_irs`` renders the pane the user pushes to and deletes
    from — neither may silently under-report. Pinned as source rather than
    behavior because the default is the engine's, so a port that simply drops
    the keyword reads as working."""
    source = inspect.getsource(getattr(RealDevicePort, verb))
    assert f"{listing}(strict=True)" in source


def test_list_device_irs_strict_failure_reports_instead_of_going_offline(tmp_home, monkeypatch):
    """A strict listing raising on a truncated reply is an abort on a REACHABLE
    device. ``_session`` used to map every HelixError to DeviceUnreachable, so
    refreshing the IRs tab over one dropped frame blanked the whole app; the
    error must reach ``DeviceService.query``'s error branch instead, which
    reports it and leaves connectivity alone."""
    from helixgen.device import HelixError

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    _connectable_client(monkeypatch)

    def boom(self, ip):
        raise HelixError("malformed device reply: truncated chunked payload")

    monkeypatch.setattr(RealDevicePort, "_session", contextmanager(boom))
    with pytest.raises(HelixError):
        build_core().device.list_device_irs()


def test_probe_survives_a_non_connect_failure_instead_of_killing_its_thread(monkeypatch):
    """``_session`` no longer converts every HelixError, so ``probe`` can now
    raise one. ``DeviceService._probe_once`` runs on a daemon thread and caught
    only DeviceUnreachable — an escaping error killed the poller silently and
    froze the header on its last state forever."""
    from helixgen.device import HelixError

    from helixgen_tui.core.device import DeviceService

    seen = []

    class _Port:
        def probe(self):
            raise HelixError("malformed device reply")

    service = DeviceService(_Port(), on_state=seen.append, spawn=lambda fn: fn(), timeout=1.0)
    service.start()
    assert seen and seen[-1].status == "offline"


def test_plan_sync_all_raises_rather_than_planning_over_a_broken_manifest(tmp_home, monkeypatch):
    """A destructive-confirm preview must RAISE on anything the confirm can't
    survive (the ``plan_prune_irs`` rule). Swallowing the failure rendered the
    literal "(no setlists to sync)" — indistinguishable from a genuinely empty
    manifest — behind a confirm that then ran a real sync."""
    from helixgen.device import manifest as manifest_mod

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")

    def boom(*a, **k):
        raise KeyError("tones")

    monkeypatch.setattr(manifest_mod.SetlistManifest, "load", staticmethod(boom))
    with pytest.raises(KeyError):
        build_core().device.plan_sync_all(gc=True)


def test_plan_sync_all_lists_only_the_setlists_sync_all_will_touch(tmp_home, monkeypatch):
    """The confirm runs ``sync_setlists(setlists=None)``, which maintains only
    ``synced=True`` setlists — pinned against the engine's own source below.
    Listing drafts promised a sync the device never gets, and the footer then
    reported success over them."""
    import inspect

    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    src = inspect.getsource(setlist_sync.sync_setlists)
    assert "if manifest.is_synced(s)" in src, "engine's --all target selection changed"

    _seed_tone_in_setlist("Gig 1", synced=True, stem="gig-tone", preset="Gig Tone")
    _seed_tone_in_setlist("Draft", synced=False, stem="draft-tone", preset="Draft Tone")

    plan = build_core().device.plan_sync_all(gc=False)
    assert any(line.startswith("Gig 1 (") for line in plan.lines), plan.lines
    assert not any(line.startswith("Draft (") for line in plan.lines), plan.lines

"""build_core() wiring: real library/setlists + the offline-first RealDevicePort.

Every test here forces the OFFLINE state (no device record, and the ambient
``$HELIXGEN_HELIX_IP`` is deleted so a dev machine pointed at the real Helix
can't leak a connection). The networked verbs are checked only for their
offline behavior and their signatures — never driven against hardware.
"""

from __future__ import annotations

import inspect

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
        return [{"outcome": "uploaded"}]

    monkeypatch.setattr(ir_upload, "upload_missing_irs", fake_upload)

    result = build_core().device.push_ir("V30 Cab")  # the stem, as the screen sends
    assert result.ok is True
    assert captured["hashes"] == [irhash]


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


def _canned_report(*, installed=(), updated=(), skipped=(), errors=()):
    return {
        "ok": not errors,
        "setlists": [],
        "pool": {
            "installed": list(installed),
            "updated": list(updated),
            "skipped": list(skipped),
            "deleted": [],
            "delete_skipped": [],
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


def test_sync_all_failures_flip_ok_false_and_are_counted(tmp_home, monkeypatch):
    from helixgen.device import setlist_sync

    monkeypatch.setenv("HELIXGEN_HELIX_IP", "10.255.255.1")
    report = _canned_report(skipped=["x"], errors=["tone 'x': install failed"])
    monkeypatch.setattr(setlist_sync, "sync_setlists", lambda *a, **k: report)

    result = build_core().device.sync_all(gc=False)
    assert result.ok is False
    assert "1 failed" in result.message
    assert "1 skipped" in result.message


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

"""build_core(): the real Core wiring for the TUI.

Library and setlists are real adapters over the installed helixgen package; the
device port is ``RealDevicePort`` over helixgen's device client. It is
offline-first: with no device configured (no ``--ip``/``$HELIXGEN_HELIX_IP``/no
discovered record), ``probe`` raises ``DeviceUnreachable`` immediately — no
socket — so the app comes up offline and ``build_core()`` still works.

Every networked verb is a thin delegation to the helixgen device layer
(``HelixClient``, ``setlist_sync``, ``maintenance``, ``backup``, ``locks``) per
docs/superpowers/plans/core-api-notes.md — signature-verified only, never run
against hardware in this build. ``make_active`` is the one place that references
core's load verb (``HelixClient.load_preset``); it must never touch a real Helix
here. All the connection/failure mapping funnels through ``_session``.
"""

from __future__ import annotations

import pathlib
from contextlib import contextmanager
from typing import Iterator

from helixgen_tui.core.editor import RealEditor
from helixgen_tui.core.library import RealLibrary
from helixgen_tui.core.models import DeviceStateVM, IrVM, MutationPlan, OpResult
from helixgen_tui.core.ports import Core, DeviceUnreachable
from helixgen_tui.core.setlists import RealSetlists

_RESTORE_UNSUPPORTED = (
    "restore needs a target preset (cid) the port contract can't carry yet — "
    "use `helixgen device restore <file> <cid>`"
)


class RealDevicePort:
    """DevicePort over helixgen's device client. Offline-first, thin per verb."""

    def __init__(self, port: int = 2002) -> None:
        self._port = port

    # -- connection plumbing ----------------------------------------------

    def _resolve_ip(self) -> str:
        """The device IP via helixgen's resolution chain, or DeviceUnreachable —
        immediately and without a socket — when nothing is configured (the
        offline-first hinge)."""
        from helixgen.device import discovery

        try:
            return discovery.resolve_ip()
        except discovery.IPResolutionError as exc:
            raise DeviceUnreachable(str(exc)) from exc

    @contextmanager
    def _session(self, ip: str) -> Iterator[object]:
        """A connected ``HelixClient`` context; connect/socket failures become
        ``DeviceUnreachable`` (so DeviceService flips the app offline)."""
        from helixgen.device import HelixClient, HelixError

        try:
            with HelixClient(ip, self._port) as client:
                yield client
        except (HelixError, OSError) as exc:
            raise DeviceUnreachable(str(exc)) from exc

    def _op(self, label: str, fn) -> OpResult:
        """Run a mutating device closure -> OpResult. Connect failures raise
        DeviceUnreachable (offline); anything else fails soft as ok=False."""
        from helixgen.device import HelixError

        try:
            return fn()
        except DeviceUnreachable:
            raise
        except (HelixError, OSError) as exc:
            raise DeviceUnreachable(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — surfaced to the footer as ok=False
            return OpResult(ok=False, message=f"{label} failed: {exc}")

    # -- read / status -----------------------------------------------------

    def probe(self) -> DeviceStateVM:
        ip = self._resolve_ip()  # DeviceUnreachable offline — no socket
        with self._session(ip) as client:
            info = client.product_info() or {}
            try:
                active = client.active_preset() or {}
            except Exception:  # noqa: BLE001 — active tone is advisory
                active = {}
        model = info.get("helixgen_model") or info.get("model")
        return DeviceStateVM(
            status="connected",
            model=str(model) if model else None,
            address=ip,
            active_tone=(active.get("name") or None),
            detail="",
        )

    def info(self) -> dict[str, str]:
        ip = self._resolve_ip()
        with self._session(ip) as client:
            info = client.product_info() or {}
        return {str(k): str(v) for k, v in info.items()}

    def list_device_irs(self) -> list[IrVM]:
        ip = self._resolve_ip()
        with self._session(ip) as client:
            rows = client.list_irs()
        return [
            IrVM(name=r.get("name") or "", pack=None, irhash=r.get("hash"), on_device=True)
            for r in rows
        ]

    def lock_status(self) -> list[str]:
        """Advisory device leases — fully offline (local lock files); an
        unconfigured device just has no leases."""
        from helixgen import locks

        try:
            ip = self._resolve_ip()
        except DeviceUnreachable:
            return []
        return [locks.describe(lease) for lease in locks.status(ip)]

    # -- activate / sync ---------------------------------------------------

    def _pool_cid_for(self, client, tone_id: str) -> int | None:
        for row in client.list_presets():
            if row.get("name") == tone_id:
                return row.get("cid_")
        return None

    def make_active(self, tone_id: str) -> OpResult:
        def _run() -> OpResult:
            ip = self._resolve_ip()
            with self._session(ip) as client:
                cid = self._pool_cid_for(client, tone_id)
                if cid is None:
                    return OpResult(ok=False, message=f"{tone_id!r} is not on the device")
                # The load verb — the ONLY reference to it; never run on hardware here.
                ok = client.load_preset(cid)
            return OpResult(
                ok=bool(ok),
                message=(f"made {tone_id!r} active" if ok else f"could not activate {tone_id!r}"),
            )

        return self._op("make_active", _run)

    def _synced_setlists_with_tone(self, tone_id: str) -> list[str]:
        """The setlists that contain ``tone_id`` AND are already opted into
        mirroring (``synced=True``).

        A *targeted* ``sync_setlists`` call flips its named setlists to
        ``synced`` as a side effect (core's opt-in gesture), so syncing a tone
        via a draft setlist would silently enable mirroring on it. Restricting
        to already-synced setlists keeps that opt-in an explicit Setlists-screen
        action."""
        from helixgen.device.manifest import SetlistManifest

        manifest = SetlistManifest.load()
        return [
            s
            for s in manifest.setlists()
            if tone_id in manifest.tones_in(s) and manifest.is_synced(s)
        ]

    @staticmethod
    def _summarize_sync_report(report: dict, label: str) -> OpResult:
        """Fold ``setlist_sync.sync_setlists``'s report into an OpResult.

        The report's shape (helixgen 0.26) is
        ``{ok, pool:{installed,updated,skipped,...}, errors:[...], ...}`` with
        per-tone install/update/IR failures accumulated in ``errors`` (``ok`` is
        ``not errors``). We surface the four bucket counts the user cares about
        and fail the op (``ok=False``) whenever anything failed — previously the
        whole report was discarded and every sync reported a bare success."""
        pool = report.get("pool") or {}
        installed = len(pool.get("installed") or [])
        updated = len(pool.get("updated") or [])
        skipped = len(pool.get("skipped") or [])
        failed = len(report.get("errors") or [])
        summary = (
            f"{installed} installed, {updated} updated, "
            f"{skipped} skipped, {failed} failed"
        )
        return OpResult(ok=failed == 0, message=f"{label} — {summary}")

    def _sync(self, setlists: list[str] | None, gc: bool, label: str) -> OpResult:
        def _run() -> OpResult:
            from helixgen.device import setlist_sync
            from helixgen.device.manifest import SetlistManifest

            ip = self._resolve_ip()
            manifest = SetlistManifest.load()
            report = setlist_sync.sync_setlists(
                manifest, ip=ip, port=self._port, setlists=setlists, gc=gc
            )
            return self._summarize_sync_report(report, label)

        return self._op("sync", _run)

    def sync_tone(self, tone_id: str) -> OpResult:
        setlists = self._synced_setlists_with_tone(tone_id)
        if not setlists:
            return OpResult(
                ok=False,
                message=(
                    f"{tone_id!r} is in no synced setlist — sync a setlist from "
                    f"the Setlists screen"
                ),
            )
        return self._sync(setlists, gc=False, label=f"synced {tone_id!r}")

    def sync_setlist(self, name: str, gc: bool) -> OpResult:
        return self._sync([name], gc=gc, label=f"synced setlist {name!r}")

    def sync_all(self, gc: bool) -> OpResult:
        return self._sync(None, gc=gc, label="synced all setlists")

    def plan_sync_all(self, gc: bool) -> MutationPlan:
        from helixgen.device.manifest import SetlistManifest

        try:
            manifest = SetlistManifest.load()
            lines: tuple[str, ...] = tuple(
                f"{s} ({len(manifest.tones_in(s))} tones)" for s in manifest.setlists()
            )
        except Exception:  # noqa: BLE001 — planning is best-effort/offline
            lines = ()
        lines = lines or ("(no setlists to sync)",)
        if gc:
            lines = (*lines, "GC: remove pool presets no setlist references")
        return MutationPlan(title="Sync all setlists to the device", lines=lines)

    # -- tone deletion (device-side) --------------------------------------

    def plan_delete_tone(self, tone_id: str) -> MutationPlan:
        return MutationPlan(
            title="Delete tone from the device",
            lines=(f"Remove {tone_id!r} from the device pool.",),
        )

    def delete_tone(self, tone_id: str) -> OpResult:
        # No public single-pool-preset delete on the client; the CLI drives it
        # through private ledger helpers. Kept honest until a device-screen flow
        # binds it directly.
        return OpResult(
            ok=False,
            message=f"deleting {tone_id!r} from the device isn't wired to the TUI yet",
        )

    # -- IRs (device-side) -------------------------------------------------

    @staticmethod
    def _resolve_ir_hash(mapping, ir_name: str) -> str | None:
        """The registered IR hash for ``ir_name``, matching (in preference order)
        the mapping's hash key, a registered file's basename, or its stem.

        The screen sends ``IrVM.name`` — a *stem* (``Path(wav).stem``, no
        extension) — but ``IrMapping.resolve_by_basename`` compares against the
        full ``os.path.basename`` (with extension), so a stem never matched and
        every push failed. Resolving here across all three keys (hash first)
        fixes that without changing the port signature."""
        import os

        entries = mapping.entries
        if ir_name in entries:  # already an irhash — prefer it
            return ir_name
        for irhash, wav_path in entries.items():
            basename = os.path.basename(str(wav_path))
            if basename == ir_name or os.path.splitext(basename)[0] == ir_name:
                return irhash
        return None

    def push_ir(self, ir_name: str) -> OpResult:
        def _run() -> OpResult:
            from helixgen.device import ir_upload
            from helixgen.ir import IrMapping

            ip = self._resolve_ip()
            mapping = IrMapping.load()
            irhash = self._resolve_ir_hash(mapping, ir_name)
            if irhash is None:
                return OpResult(ok=False, message=f"no registered IR named {ir_name!r}")
            import os

            results = ir_upload.upload_missing_irs(ip, [irhash])
            ok = all(r.get("outcome") != "upload_error" for r in results)
            # ir_name may be a raw irhash (the screen pushes by hash so
            # duplicate display names stay unambiguous) — report the
            # registered file's stem instead.
            label = os.path.splitext(os.path.basename(str(mapping.entries[irhash])))[0]
            msg = f"pushed IR {label!r}" if ok else f"IR {label!r} upload failed"
            return OpResult(ok=ok, message=msg)

        return self._op("push_ir", _run)

    def plan_delete_ir(self, ir_name: str) -> MutationPlan:
        return MutationPlan(
            title="Delete IR from the device",
            lines=(f"Remove {ir_name!r} from the device (registry + file).",),
        )

    def delete_ir(self, ir_name: str) -> OpResult:
        def _run() -> OpResult:
            from helixgen.device import maintenance

            ip = self._resolve_ip()
            with self._session(ip) as client:
                maintenance.delete_device_ir(client, ir_name, ip=ip)
            return OpResult(ok=True, message=f"deleted IR {ir_name!r}")

        return self._op("delete_ir", _run)

    def plan_prune_irs(self) -> MutationPlan:
        def _run() -> MutationPlan:
            from helixgen.device import maintenance

            ip = self._resolve_ip()
            report = maintenance.ir_prune(ip=ip, port=self._port, execute=False)
            prunable = report.get("prunable") or report.get("prune") or []
            lines = tuple(str(x.get("name", x)) for x in prunable) if prunable else (
                "(no unreferenced device IRs to prune)",
            )
            return MutationPlan(title="Prune unreferenced device IRs", lines=lines)

        try:
            return _run()
        except Exception:  # noqa: BLE001 — offline/planning is best-effort
            return MutationPlan(
                title="Prune unreferenced device IRs",
                lines=("(device unreachable — connect to preview the prune)",),
            )

    def prune_irs(self) -> OpResult:
        def _run() -> OpResult:
            from helixgen.device import maintenance

            ip = self._resolve_ip()
            maintenance.ir_prune(ip=ip, port=self._port, execute=True)
            return OpResult(ok=True, message="pruned unreferenced device IRs")

        return self._op("prune_irs", _run)

    def rename_ir(self, ir_name: str, new_name: str) -> OpResult:
        def _run() -> OpResult:
            from helixgen.device import maintenance

            ip = self._resolve_ip()
            with self._session(ip) as client:
                match = maintenance.resolve_device_ir_live(client, ir_name)
                cid = match.get("cid_")
                ok = bool(cid is not None and client.rename(cid, new_name))
            return OpResult(
                ok=ok,
                message=(f"renamed IR to {new_name!r}" if ok else f"could not rename {ir_name!r}"),
            )

        return self._op("rename_ir", _run)

    # -- backup / restore --------------------------------------------------

    def backup(self) -> OpResult:
        def _run() -> OpResult:
            from helixgen.device import backup as _backup

            ip = self._resolve_ip()
            with self._session(ip) as client:
                entries = _backup.backup_setlist(client)
            return OpResult(ok=True, message=f"backed up {len(entries)} preset(s)")

        return self._op("backup", _run)

    def plan_restore(self, file: str) -> MutationPlan:
        return MutationPlan(title="Restore preset from file", lines=(_RESTORE_UNSUPPORTED,))

    def restore(self, file: str) -> OpResult:
        return OpResult(ok=False, message=_RESTORE_UNSUPPORTED)


class RealCore:
    """Core over the local helixgen home; offline-first RealDevicePort."""

    def __init__(self) -> None:
        self.library = RealLibrary()
        self.setlists = RealSetlists()
        self.device = RealDevicePort()
        self.editor = RealEditor()

    def list_local_irs(self) -> list[IrVM]:
        """Registered user IRs from mapping.json, enriched from IR sidecars.

        on_device is always None here (offline — unknown until a real device
        port reports).
        """
        from helixgen.ir import IrMapping
        from helixgen.ir_meta import load_all_ir_metas

        try:
            mapping = IrMapping.load()
            metas = {m.irhash: m for m in load_all_ir_metas()}
        except Exception:
            return []
        irs: list[IrVM] = []
        for irhash, wav_path in sorted(mapping.entries.items(), key=lambda kv: str(kv[1]).lower()):
            name = pathlib.Path(str(wav_path)).stem
            meta = metas.get(irhash)
            pack = None
            if meta is not None and isinstance(meta.pack, dict):
                raw = meta.pack.get("name") or meta.pack.get("slug")
                pack = str(raw) if raw else None
            irs.append(IrVM(name=name, pack=pack, irhash=irhash, on_device=None))
        return irs


def build_core() -> Core:
    """The real Core the TUI runs against."""
    return RealCore()

"""build_core(): the real Core wiring for the TUI.

Library and setlists are real adapters over the installed helixgen package; the
device port is ``RealDevicePort`` over helixgen's device client. It is
offline-first: with no device configured (no ``--ip``/``$HELIXGEN_HELIX_IP``/no
discovered record), ``probe`` raises ``DeviceUnreachable`` immediately — no
socket — so the app comes up offline and ``build_core()`` still works.

Every networked verb is a thin delegation to the helixgen device layer
(``HelixClient``, ``setlist_sync``, ``maintenance``, ``backup``, ``locks``) per
docs/superpowers/plans/core-api-notes.md. The opt-in live suite
(``tests/live/``, ``HELIXGEN_TUI_LIVE=1``) exercises these verbs — including
``make_active``'s ``HelixClient.load_preset`` — against a real Helix; the
default offline run never can.

Failure classification happens ONCE, in ``_session`` (and in the two verbs that
connect themselves, ``plan_prune_irs``/``ir_prune``): only a connect-class
failure is ``DeviceUnreachable``. Every other engine error propagates so the
caller can fail soft with the engine's remediation text — ``_op`` turns it into
``OpResult(ok=False)`` for mutations, and ``DeviceService.query``'s error branch
reports it for reads, neither of which flips the app offline.

``push_ir`` is the one verb that can't classify: ``upload_missing_irs`` opens
its own connection and never raises — a connect fault comes back as a per-hash
``ok=False`` with the reason in ``note`` — so a device that vanished mid-push
reports the engine's note and the header corrects on the next probe.
"""

from __future__ import annotations

import errno
import pathlib
import socket
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


#: The engine's connect-class ``HelixError`` messages — the only ones that mean
#: the device is GONE (``HelixClient.connect``/``_open_socket``/``_rpc`` after
#: its reconnects are exhausted). Every other ``HelixError`` is an abort on a
#: REACHABLE device — a strict listing on a truncated reply, a dangling setlist
#: reference, an incomplete pool listing, the prune confirm re-scan disagreeing
#: — and mapping those to unreachable flips the whole app offline over a healthy
#: device while discarding the engine's remediation text. Enumerating the
#: connect messages is a closed set; enumerating the aborts is not (they grow
#: with the engine). ``tests/core/test_real_core.py`` pins these against the
#: installed ``HelixClient`` source so a reword can't silently un-classify them.
_CONNECT_FAILURES = (
    "no Helix Stadium answered",
    "could not open device socket",
    "device connection lost after",
)


def _is_connect_failure(exc: Exception) -> bool:
    return any(marker in str(exc) for marker in _CONNECT_FAILURES)


#: The ``OSError`` errnos that mean TRANSPORT — the network half of the device
#: layer. It also does LOCAL disk work under the same guards
#: (``backup_setlist``'s mkdir + write_bytes, ``IrMapping.load``,
#: ``ir_prune``'s manifest reads), so a blanket ``except OSError -> offline``
#: reported ENOSPC/EACCES/EROFS as "device offline" — the exact
#: misclassification ``_CONNECT_FAILURES`` exists to prevent, on the verbs with
#: the largest non-network OSError surface. Classifying on the errno rather
#: than the class is deliberate: ``ConnectionError`` misses EHOSTUNREACH and
#: ENETUNREACH (a device simply off the LAN), which arrive as a plain
#: ``OSError``. Like the connect messages, the transport errnos are a closed
#: set and the local-disk ones are not.
_TRANSPORT_ERRNOS = frozenset(
    {
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.ECONNABORTED,
        errno.EHOSTUNREACH,
        errno.EHOSTDOWN,
        errno.ENETUNREACH,
        errno.ENETDOWN,
        errno.ENETRESET,
        errno.ETIMEDOUT,
        errno.EPIPE,
    }
)


def _is_transport_oserror(exc: OSError) -> bool:
    """True for an OSError that means the device is unreachable. A DNS failure
    always is; otherwise it must carry a transport errno — an OSError with no
    errno at all is treated as local, so an unlabelled disk failure fails soft
    rather than blanking the app."""
    return isinstance(exc, socket.gaierror) or exc.errno in _TRANSPORT_ERRNOS


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
        """A connected ``HelixClient`` context, and the ONE place device
        failures get classified.

        Only a connect-class failure becomes ``DeviceUnreachable`` (so
        DeviceService flips the app offline). Every other ``HelixError`` — a
        strict listing on a truncated reply, a malformed frame, the engine
        refusing an operation — is an abort on a REACHABLE device and
        propagates unchanged, so ``_op`` can fail it soft and
        ``DeviceService.query``'s error branch can report it without the header
        lying about connectivity."""
        from helixgen.device import HelixClient, HelixError

        try:
            with HelixClient(ip, self._port) as client:
                yield client
        except HelixError as exc:
            if _is_connect_failure(exc):
                raise DeviceUnreachable(str(exc)) from exc
            raise
        except OSError as exc:
            if _is_transport_oserror(exc):
                raise DeviceUnreachable(str(exc)) from exc
            raise

    def _op(self, label: str, fn) -> OpResult:
        """Run a mutating device closure -> OpResult. Connect failures raise
        DeviceUnreachable (offline); anything else fails soft as ok=False,
        keeping the engine's remediation text."""
        from helixgen.device import HelixError

        try:
            return fn()
        except DeviceUnreachable:
            raise
        except HelixError as exc:
            # The verbs that connect themselves (``sync``, ``push_ir``,
            # ``prune_irs``) never pass through ``_session``, so classify here
            # too — same rule, same closed set of connect markers.
            if _is_connect_failure(exc):
                raise DeviceUnreachable(str(exc)) from exc
            return OpResult(ok=False, message=f"{label} failed: {exc}")
        except OSError as exc:
            if _is_transport_oserror(exc):
                raise DeviceUnreachable(str(exc)) from exc
            return OpResult(ok=False, message=f"{label} failed: {exc}")
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
        # strict=True: the default listing reads a timeout or a truncated reply
        # as an empty list, and this pane is what the user then pushes to and
        # deletes from — an IR silently missing from it is worse than an error.
        ip = self._resolve_ip()
        with self._session(ip) as client:
            rows = client.list_irs(strict=True)
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
        # strict=True: a missing row here becomes the definitive claim "'X' is
        # not on the device". The default listing reads a timeout or a
        # truncated reply as empty/partial, which would make that claim false
        # on a healthy device; strict raises instead and the abort fails soft
        # with the engine's retry text.
        for row in client.list_presets(strict=True):
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

        The report's shape is ``{ok, pool:{installed,updated,skipped,deleted,
        delete_skipped}, errors:[...], ...}`` with per-tone install/update/IR
        failures accumulated in ``errors`` (``ok`` is ``not errors``). We
        surface every bucket count and fail the op (``ok=False``) whenever
        anything failed — previously the whole report was discarded and every
        sync reported a bare success.

        Two buckets are not decoration. ``deleted`` is the managed-set mirror
        delete — the ordinary "unsync a tone, then sync" flow — so dropping it
        reported "0 installed, 0 updated, 0 skipped" over a sync that removed
        presets from the device. ``delete_skipped`` is the engine *refusing* a
        delete (a live setlist still references the preset) and it is NOT
        appended to ``errors``, so folding only ``errors`` reported success
        while the tone stayed on the device — the same "success over an engine
        refusal" class the IR verbs were fixed for."""
        pool = report.get("pool") or {}
        installed = len(pool.get("installed") or [])
        updated = len(pool.get("updated") or [])
        skipped = len(pool.get("skipped") or [])
        deleted = len(pool.get("deleted") or [])
        refused = [str(n) for n in (pool.get("delete_skipped") or [])]
        errors = [str(e) for e in (report.get("errors") or [])]
        failed = len(errors)
        summary = (
            f"{installed} installed, {updated} updated, {deleted} deleted, "
            f"{skipped} skipped, {failed} failed"
        )
        if errors:
            # The footer is the only diagnostic surface in the app: a bare
            # "2 failed" leaves no way to learn WHICH tones failed or why, and
            # an IR-upload soft failure inside a sync (the same `note` push_ir
            # surfaces) would be invisible. Same fold as `prune_irs`.
            summary += f": {errors[0]}"
        if refused:
            summary += (
                " — still on the device, a live setlist references them: "
                + ", ".join(refused)
            )
        return OpResult(ok=failed == 0 and not refused, message=f"{label} — {summary}")

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
        """The preview behind the sync-all ConfirmModal — so a planning failure
        RAISES rather than becoming plan text (same rule as
        ``plan_prune_irs``). Swallowing a broken manifest rendered the literal
        "(no setlists to sync)" and then let the confirm run a real sync,
        indistinguishable from the genuine empty case.

        Only ``synced=True`` setlists are listed, because that is exactly what
        the confirm then runs: ``sync_setlists(setlists=None)`` maintains the
        mirror-enabled setlists and never touches local-only drafts. Previewing
        every manifest setlist promised drafts would sync, and the footer then
        reported success over setlists the device never saw."""
        from helixgen.device.manifest import SetlistManifest

        manifest = SetlistManifest.load()
        lines: tuple[str, ...] = tuple(
            f"{s} ({len(manifest.tones_in(s))} tones)"
            for s in manifest.setlists()
            if manifest.is_synced(s)
        ) or ("(no synced setlists to sync)",)
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
        entries = mapping.entries
        if ir_name in entries:  # already an irhash — prefer it
            return ir_name
        for irhash, wav_path in entries.items():
            path = pathlib.PurePath(str(wav_path))
            if path.name == ir_name or path.stem == ir_name:
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
            results = ir_upload.upload_missing_irs(ip, [irhash])
            # the engine's per-hash ``ok`` is True only for "already"/
            # "imported" — soft failures (upload_failed, not_yet_registered,
            # hash_mismatch, ...) carry ok=False with the reason in ``note``
            ok = bool(results) and all(r.get("ok") for r in results)
            # ir_name may be a raw irhash (the screen pushes by hash so
            # duplicate display names stay unambiguous) — report the
            # registered file's stem instead.
            label = pathlib.PurePath(str(mapping.entries[irhash])).stem
            if ok:
                msg = f"pushed IR {label!r}"
            else:
                note = next(
                    (r["note"] for r in results if not r.get("ok") and r.get("note")),
                    "upload failed",
                )
                msg = f"IR {label!r}: {note}"
            return OpResult(ok=ok, message=msg)

        return self._op("push_ir", _run)

    def plan_delete_ir(self, ir_name: str) -> MutationPlan:
        return MutationPlan(
            title="Delete IR from the device",
            # Best-effort on the file half deliberately: ``delete_device_ir``'s
            # SFTP step needs a usable hedit key and commonly can't run, so the
            # registry entry goes and the .wav stays. Promising both here made
            # the routine outcome look like a partial failure.
            lines=(
                f"Remove {ir_name!r} from the device registry "
                f"(the backing file too, if it can be reached).",
            ),
        )

    def delete_ir(self, ir_name: str) -> OpResult:
        def _run() -> OpResult:
            from helixgen.device import maintenance

            ip = self._resolve_ip()
            with self._session(ip) as client:
                report = maintenance.delete_device_ir(client, ir_name, ip=ip)
            # the engine returns ``ok = bool(client.delete_irs([cid]))`` — a
            # device that refuses the removal does NOT raise, so a discarded
            # report reported success over an IR still on the device.
            ok = bool(report.get("ok"))
            if not ok:
                return OpResult(ok=False, message=f"device refused to delete IR {ir_name!r}")
            # ``file_removed`` is the advisory SFTP half: registry gone but the
            # backing .wav left behind is the wedged state the engine needs
            # --force-wedge to clean, so don't report it as a clean delete.
            suffix = (
                ""
                if report.get("file_removed")
                else " (registry entry removed; backing file left on the device)"
            )
            return OpResult(ok=True, message=f"deleted IR {ir_name!r}{suffix}")

        return self._op("delete_ir", _run)

    def plan_prune_irs(self) -> MutationPlan:
        """The preview behind a destructive ConfirmModal — so a planning
        failure RAISES rather than becoming plan text: the caller runs this
        through ``DeviceService.query``, which reports the failure and never
        opens the modal. Swallowing it offered a confirmable prune with no
        preview of what the confirm would delete."""
        from helixgen.device import HelixError, maintenance

        ip = self._resolve_ip()
        try:
            report = maintenance.ir_prune(ip=ip, port=self._port, execute=False)
        except HelixError as exc:
            # This half runs FIRST, and ir_prune connects itself (no _session):
            # without the split, a device off the LAN raises past DeviceService
            # as a generic error and the header keeps claiming "connected".
            if _is_connect_failure(exc):
                raise DeviceUnreachable(str(exc)) from exc
            raise
        except OSError as exc:
            # ir_prune's SFTP/socket half can surface an OSError the engine
            # never wraps; every sibling path treats a TRANSPORT one as offline
            # and lets a local-disk one (its manifest reads) fail as itself.
            if _is_transport_oserror(exc):
                raise DeviceUnreachable(str(exc)) from exc
            raise
        # The dry-run report is ``{ok, dry_run, device_irs, referenced,
        # protected, orphans, deleted, warnings, errors}`` — the delete
        # candidates are ``orphans`` (``protected`` needs force, which
        # this port never passes). The keys this used to read
        # ("prunable"/"prune") have never existed, so the confirm modal
        # for a destructive verb always claimed there was nothing to
        # prune while the confirm went on to delete for real.
        warnings = report.get("warnings") or []
        if warnings:
            # A warning means the confirm CANNOT succeed: ir_prune(execute=True)
            # raises "refusing to execute: ..." over unverifiable local IR
            # references unless ignore_warnings is passed, and this port never
            # passes it (that would be failing open on a destructive verb).
            # Rendering them as plan lines opened a confirm doomed to refuse.
            raise RuntimeError(
                "cannot plan a prune: some local tones' IR references could not "
                "be verified, so the prune would refuse to execute — "
                + "; ".join(str(w) for w in warnings)
            )
        lines = tuple(
            f"Delete {str(o.get('name') or o.get('hash'))!r} from the device."
            for o in (report.get("orphans") or [])
        ) or ("(no unreferenced device IRs to prune)",)
        return MutationPlan(title="Prune unreferenced device IRs", lines=lines)

    def prune_irs(self) -> OpResult:
        def _run() -> OpResult:
            from helixgen.device import maintenance

            # No local try/except: ``_op`` already applies the one
            # classification rule (connect-class -> offline, every other abort
            # soft with the engine's remediation text). A second copy here just
            # had to be kept in sync, on a destructive verb.
            ip = self._resolve_ip()
            report = maintenance.ir_prune(ip=ip, port=self._port, execute=True)
            # Per-IR delete refusals accumulate in ``errors`` and set
            # ``ok=False`` WITHOUT raising (same class as the push_ir fix).
            errors = report.get("errors") or []
            deleted = report.get("deleted") or []
            message = f"pruned {len(deleted)} unreferenced device IR(s)"
            # ``ir_prune`` records the advisory SFTP half per deleted entry
            # (``entry["file_removed"]``), exactly as ``delete_device_ir`` does.
            # Counting only the entries reported a clean prune over N registry
            # rows removed with their .wav files left behind — the wedged state
            # the engine needs --force-wedge to clean, and the same fold
            # ``delete_ir`` already applies on the single-IR sibling.
            wedged = sum(1 for e in deleted if not (e or {}).get("file_removed"))
            if wedged:
                message += f" ({wedged} backing file(s) left on the device)"
            if errors:
                message = f"{message} — {len(errors)} failed: {errors[0]}"
            return OpResult(ok=not errors, message=message)

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
                # strict=True, for the same reason as `list_device_irs`, only
                # worse here: `backup_setlist`'s own listing is the engine's
                # non-strict default, which reads a timeout or a truncated
                # reply as an EMPTY list. A dropped frame then backs up nothing
                # and this reports a green "backed up 0 preset(s)" over the
                # user's only restore point, immediately before they
                # prune/sync/delete. Strict raises instead, and the abort fails
                # soft with the engine's retry text.
                entries = _backup.backup_setlist(
                    client, presets=client.list_presets(strict=True)
                )
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

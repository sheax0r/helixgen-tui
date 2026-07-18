"""RealSetlists: SetlistPort over helixgen's setlist manifest (v3).

Every method loads the manifest fresh from disk and saves after a successful
mutation, so state is always consistent with other helixgen surfaces (CLI,
skills) touching the same home. Unknown setlist/tone names come back as
OpResult(ok=False, ...) — the port never raises, and never creates a setlist
as a side effect (manifest.add_to_setlist would; we guard first — see
docs/superpowers/plans/core-api-notes.md).
"""

from __future__ import annotations

from helixgen_tui.core.models import OpResult, SetlistVM


class RealSetlists:
    """SetlistPort adapter over helixgen.device.manifest.SetlistManifest."""

    def list_setlists(self) -> list[SetlistVM]:
        from helixgen.device.manifest import SetlistManifest

        manifest = SetlistManifest.load()
        return [
            SetlistVM(
                name=name,
                sync_enabled=manifest.is_synced(name),
                tones=tuple(manifest.tones_in(name)),
            )
            for name in manifest.setlists()
        ]

    def add_tone(self, setlist: str, tone_id: str) -> OpResult:
        from helixgen.device.manifest import SetlistManifest

        try:
            manifest = SetlistManifest.load()
            if setlist not in manifest.setlists():
                return OpResult(ok=False, message=f"unknown setlist {setlist!r}")
            if tone_id in manifest.tones_in(setlist):
                return OpResult(ok=False, message=f"{tone_id!r} is already in {setlist!r}")
            manifest.add_to_setlist(setlist, tone_id)
            manifest.save()
        except Exception as exc:
            return OpResult(ok=False, message=str(exc))
        return OpResult(ok=True, message=f"added {tone_id!r} to {setlist!r}")

    def remove_tone(self, setlist: str, tone_id: str) -> OpResult:
        from helixgen.device.manifest import SetlistManifest

        try:
            manifest = SetlistManifest.load()
            if setlist not in manifest.setlists():
                return OpResult(ok=False, message=f"unknown setlist {setlist!r}")
            # Membership removal only (never the registry-GC'ing legacy
            # manifest.remove_tone) — leaving a setlist must not make a tone
            # vanish from the library.
            if not manifest.remove_from_setlist(setlist, tone_id):
                return OpResult(ok=False, message=f"{tone_id!r} is not in setlist {setlist!r}")
            manifest.save()
        except Exception as exc:
            return OpResult(ok=False, message=str(exc))
        return OpResult(ok=True, message=f"removed {tone_id!r} from {setlist!r}")

    def move_tone(self, setlist: str, tone_id: str, delta: int) -> OpResult:
        from helixgen.device.manifest import SetlistManifest

        try:
            manifest = SetlistManifest.load()
            if setlist not in manifest.setlists():
                return OpResult(ok=False, message=f"unknown setlist {setlist!r}")
            order = manifest.tones_in(setlist)
            if tone_id not in order:
                return OpResult(ok=False, message=f"{tone_id!r} is not in setlist {setlist!r}")
            index = order.index(tone_id)
            target = index + delta
            if not 0 <= target < len(order):
                return OpResult(
                    ok=False,
                    message=f"cannot move {tone_id!r} out of range in {setlist!r}",
                )
            if target == index:
                return OpResult(ok=True, message=f"{tone_id!r} unchanged")
            # The manifest has no reorder API: remove + positional re-add.
            manifest.remove_from_setlist(setlist, tone_id)
            manifest.add_to_setlist(setlist, tone_id, pos=target)
            manifest.save()
        except Exception as exc:
            return OpResult(ok=False, message=str(exc))
        return OpResult(ok=True, message=f"moved {tone_id!r} to position {target + 1}")

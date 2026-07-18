"""RealLibrary: LibraryPort over the installed helixgen package.

Reads the setlist manifest (the tone registry) and enriches each registered
tone with tone-metadata (guitar variant, description) and the *recorded*
sync state from device observation files. Everything here is offline
local-file logic — no device I/O. See docs/superpowers/plans/core-api-notes.md
for the exact helixgen API contracts this relies on.
"""

from __future__ import annotations

from helixgen_tui.core.models import SyncState, ToneVM


def _recorded_sync_state(name: str) -> SyncState:
    """Recorded-at-last-sync placement from devices/<serial>.json files.

    A hit means some device file recorded the tone as placed (SYNCED); a miss
    means no record (LOCAL_ONLY). This can be stale until the next real sync;
    drift detection is deliberately out of scope. Read failures -> UNKNOWN.
    """
    from helixgen.device import observations

    try:
        placement = observations.lookup_tone(name)
    except Exception:
        return SyncState.UNKNOWN
    return SyncState.SYNCED if placement is not None else SyncState.LOCAL_ONLY


def _variant_info(hsp_path: str | None) -> tuple[str | None, str | None]:
    """(guitar, description) for the tone whose .hsp is ``hsp_path``.

    ``guitar`` is the tone-meta variant key (a guitar slug, or None for a
    "generic"/unknown variant); ``description`` is the logical tone's
    description_md. Pathless tones (device-origin) have neither.
    """
    if not hsp_path:
        return None, None
    from helixgen import tone_meta

    try:
        hit = tone_meta.find_variant_by_hsp(hsp_path)
    except Exception:
        return None, None
    if hit is None:
        return None, None
    meta, variant_key = hit
    guitar = None if variant_key == "generic" else variant_key
    return guitar, meta.description_md


class RealLibrary:
    """LibraryPort adapter over helixgen's manifest + tone metadata."""

    def list_tones(self) -> list[ToneVM]:
        from helixgen.device.manifest import SetlistManifest

        manifest = SetlistManifest.load()
        tones: list[ToneVM] = []
        for row in manifest.library():
            name = row.get("name")
            if not name:
                continue
            guitar, description = _variant_info(manifest.tone_path(name))
            tones.append(
                ToneVM(
                    name=name,
                    tone_id=name,
                    guitar=guitar,
                    description=description,
                    sync=_recorded_sync_state(name),
                    setlists=tuple(row.get("setlists") or ()),
                )
            )
        return tones

    def get_tone(self, tone_id: str) -> ToneVM | None:
        for tone in self.list_tones():
            if tone.tone_id == tone_id:
                return tone
        return None

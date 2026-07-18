"""RealEditor: EditorPort over the installed helixgen package.

Reads a tone's signal chain from its library ``.hsp`` and writes changed params
back to it — all offline, local-file logic, no device I/O. The only helixgen
surfaces used are ``hsp`` (read/extract/write), ``library.Library`` (per-param
type/default schema), ``mutate.set_param`` (the in-place param writer), and the
setlist manifest (to locate a tone's ``.hsp``). See
docs/superpowers/specs/2026-07-18-tone-param-editor-v1-design.md for the exact
contracts and the (empirically pinned) coordinate mapping.

Coordinate mapping — the load-bearing detail: ``extract_blocks_from_hsp`` gives
each raw block an ``@path`` (the parallel *lane*) and ``@position`` (the slot
*pos*), but NOT the flow index. ``mutate.set_param`` addresses a slot by
``(name/model, path=<flow index>, lane, pos)``. So we call it with
``lane=@path, pos=@position`` and the model id — which uniquely resolves in
every normal preset. A genuinely ambiguous write (same model at the same
lane+pos across two DSP flows) raises ``MutateError``, which we surface as a
failed save rather than writing the wrong slot.
"""

from __future__ import annotations

from helixgen_tui.core.library import RealLibrary
from helixgen_tui.core.models import (
    BlockVM,
    ChainVM,
    OpResult,
    ParamChange,
    ParamVM,
    PathVM,
)

# Raw-block keys that are metadata, not editable params.
_META_KEYS = frozenset({"@model", "@type", "@position", "@path", "@enabled", "@version", "irhash"})


def _infer_type(value: object) -> str:
    """Best-effort param type when the library has no schema for the block:
    read it off the current value. ``bool`` is checked before ``int`` because
    ``bool`` is a subclass of ``int``."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


class RealEditor:
    """EditorPort adapter over helixgen's hsp/library/mutate surfaces."""

    def __init__(self) -> None:
        # Reused for the header metadata (name/guitar/setlists/description).
        self._library = RealLibrary()

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _hsp_path(tone_id: str):
        """The tone's ``.hsp`` path from the manifest, or ``None`` (device-origin
        / unregistered tones have no local file)."""
        from helixgen.device.manifest import SetlistManifest

        try:
            manifest = SetlistManifest.load()
            path = manifest.tone_path(tone_id)
        except Exception:
            return None
        return path

    @staticmethod
    def _load_library():
        from helixgen import library

        return library.Library(library.default_library_path())

    @staticmethod
    def _schema_for(lib, model: str) -> dict:
        """The ``{param: {"type","default",...}}`` schema for a model, or ``{}``
        when the block isn't catalogued (``find_block`` raises)."""
        if lib is None:
            return {}
        try:
            block = lib.find_block(model)
        except Exception:
            return {}
        return getattr(block, "params", {}) or {}

    @staticmethod
    def _display_name(lib, model: str) -> str:
        if lib is None:
            return model
        try:
            return lib.find_block(model).display_name or model
        except Exception:
            return model

    # -- reads -------------------------------------------------------------

    def get_chain(self, tone_id: str) -> ChainVM | None:
        path = self._hsp_path(tone_id)
        if not path:
            return None
        from helixgen import hsp

        body = hsp.read_hsp(path)
        raw_blocks = hsp.extract_blocks_from_hsp(body)
        lib = self._load_library()

        # Group blocks by lane (@path), preserving chain order within each lane.
        by_path: dict[int, list[BlockVM]] = {}
        for raw in raw_blocks:
            model = str(raw.get("@model", ""))
            lane = int(raw.get("@path", 0) or 0)
            position = int(raw.get("@position", 0) or 0)
            enabled = bool(raw.get("@enabled", True))
            schema = self._schema_for(lib, model)

            params: list[ParamVM] = []
            for key, value in raw.items():
                if key in _META_KEYS:
                    continue
                pschema = schema.get(key, {}) if isinstance(schema, dict) else {}
                ptype = pschema.get("type") or _infer_type(value)
                default = pschema.get("default")
                params.append(ParamVM(name=key, value=value, type=ptype, default=default))

            block = BlockVM(
                model=model,
                display=self._display_name(lib, model),
                position=position,
                path=lane,
                enabled=enabled,
                params=tuple(params),
            )
            by_path.setdefault(lane, []).append(block)

        paths = tuple(
            PathVM(path=lane, blocks=tuple(blocks)) for lane, blocks in sorted(by_path.items())
        )

        # Header metadata: reuse RealLibrary (name/guitar/description/setlists).
        tone = self._library.get_tone(tone_id)
        if tone is not None:
            name = tone.name
            guitar = tone.guitar
            description = tone.description
            setlists = tone.setlists
        else:
            name, guitar, description, setlists = tone_id, None, None, ()

        return ChainVM(
            tone_id=tone_id,
            name=name,
            guitar=guitar,
            description=description,
            setlists=setlists,
            paths=paths,
        )

    # -- writes ------------------------------------------------------------

    def save_params(self, tone_id: str, changes: list[ParamChange]) -> OpResult:
        if not changes:
            return OpResult(ok=True, message="no changes to save")
        path = self._hsp_path(tone_id)
        if not path:
            return OpResult(ok=False, message=f"{tone_id!r} has no library .hsp to edit")

        from helixgen import hsp, mutate

        try:
            body = hsp.read_hsp(path)
        except Exception as exc:  # noqa: BLE001 — surfaced to the footer
            return OpResult(ok=False, message=f"could not read tone: {exc}")

        lib = self._load_library()
        # Apply every change in memory first; a single failure aborts the whole
        # batch WITHOUT writing, so disk stays consistent (atomic save).
        for change in changes:
            try:
                mutate.set_param(
                    body,
                    change.model,
                    change.param,
                    change.value,
                    lib,
                    lane=change.path,
                    pos=change.position,
                )
            except Exception as exc:  # noqa: BLE001 — surfaced to the footer
                return OpResult(
                    ok=False,
                    message=f"could not set {change.model} {change.param}: {exc}",
                )

        try:
            hsp.write_hsp(path, body)
        except Exception as exc:  # noqa: BLE001
            return OpResult(ok=False, message=f"could not write tone: {exc}")

        n = len(changes)
        return OpResult(ok=True, message=f"saved {n} change{'s' if n != 1 else ''}")

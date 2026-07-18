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
    OutputVM,
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
    def _unwrap(wrapped):
        """Unwrap a ``.hsp`` param value (``{"value": x}`` / stereo / plain)."""
        if not isinstance(wrapped, dict):
            return wrapped
        if "value" in wrapped:
            return wrapped["value"]
        one = wrapped.get("1")
        if isinstance(one, dict) and "value" in one:
            return one["value"]
        return wrapped

    @classmethod
    def _read_output(cls, body: dict) -> OutputVM | None:
        """The terminal main-out endpoint's level (dB) + pan, read from the
        lane-0 ``b13`` output slot, falling back to the device defaults for any
        param the export omits. ``None`` when no output endpoint is present."""
        from helixgen.mutate import flowparams

        flow = (body.get("preset") or {}).get("flow") or []
        for path_dict in flow:
            if not isinstance(path_dict, dict):
                continue
            b13 = path_dict.get("b13")
            if not (isinstance(b13, dict) and b13.get("type") == "output" and b13.get("slot")):
                continue
            params = b13["slot"][0].get("params") or {}
            defaults = flowparams.OUTPUT_HSP_DEFAULTS
            gain = cls._unwrap(params.get("gain")) if "gain" in params else defaults["gain"]
            pan = cls._unwrap(params.get("pan")) if "pan" in params else defaults["pan"]
            if not isinstance(gain, (int, float)):
                gain = defaults["gain"]
            if not isinstance(pan, (int, float)):
                pan = defaults["pan"]
            return OutputVM(level=float(gain), pan=float(pan))
        return None

    @classmethod
    def _bypass_state(cls, body: dict) -> dict[tuple[int, int], bool]:
        """Map ``(lane, pos)`` to each block's device-authoritative bypass state,
        read from the ``bNN``-level ``@enabled`` wrapper — the slot Stadium reads
        for bypass, and the slot ``set_enabled`` writes. (``extract_blocks_from_hsp``
        surfaces only the *slot*-level ``@enabled``, which the bypass verb leaves
        untouched, so we read the block level directly here.)"""
        state: dict[tuple[int, int], bool] = {}
        flow = (body.get("preset") or {}).get("flow") or []
        for path_dict in flow:
            if not isinstance(path_dict, dict):
                continue
            for key, raw_block in path_dict.items():
                if not (isinstance(key, str) and key.startswith("b") and key[1:].isdigit()):
                    continue
                if not isinstance(raw_block, dict) or "@enabled" not in raw_block:
                    continue
                lane = int(raw_block.get("path", 0) or 0)
                pos = int(raw_block.get("position", 0) or 0)
                enabled = cls._unwrap(raw_block["@enabled"])
                state[(lane, pos)] = bool(enabled)
        return state

    @staticmethod
    def _read_input_source(body: dict) -> str | None:
        """The head-node instrument source (``inst1``/``inst2``/``both``/``none``)
        from the lane-0 ``b00`` input model. ``None`` when not determinable."""
        from helixgen import controllers

        device_id = (body.get("meta") or {}).get("device_id") or "stadium_xl"
        flow = (body.get("preset") or {}).get("flow") or []
        for path_dict in flow:
            if not isinstance(path_dict, dict):
                continue
            b00 = path_dict.get("b00")
            if not (isinstance(b00, dict) and b00.get("slot")):
                continue
            model = b00["slot"][0].get("model", "")
            return controllers.input_mode_for_model(device_id, model)
        return None

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
        bypass = self._bypass_state(body)

        # Group blocks by lane (@path), preserving chain order within each lane.
        by_path: dict[int, list[BlockVM]] = {}
        for raw in raw_blocks:
            model = str(raw.get("@model", ""))
            lane = int(raw.get("@path", 0) or 0)
            position = int(raw.get("@position", 0) or 0)
            # Prefer the bNN-level bypass state (what the device + the bypass verb
            # use); fall back to the slot-level flag extract surfaces.
            enabled = bypass.get((lane, position), bool(raw.get("@enabled", True)))
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
            output=self._read_output(body),
            input_source=self._read_input_source(body),
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

    def set_output(self, tone_id: str, level: float, pan: float) -> OpResult:
        """Write the main-out endpoint's level (dB) and pan to the library
        ``.hsp``. Pan is clamped to ``[0, 1]`` (mirroring the param-clamp
        discipline; ``mutate.set_flow_param`` does not clamp). Atomic: builds the
        body in memory and only writes on full success, so disk stays consistent
        on any failure."""
        path = self._hsp_path(tone_id)
        if not path:
            return OpResult(ok=False, message=f"{tone_id!r} has no library .hsp to edit")

        pan = max(0.0, min(1.0, float(pan)))

        from helixgen import hsp, mutate

        try:
            body = hsp.read_hsp(path)
        except Exception as exc:  # noqa: BLE001 — surfaced to the footer
            return OpResult(ok=False, message=f"could not read tone: {exc}")

        try:
            mutate.set_flow_param(body, "output", "level", float(level))
            mutate.set_flow_param(body, "output", "pan", pan)
        except Exception as exc:  # noqa: BLE001 — surfaced to the footer
            return OpResult(ok=False, message=f"could not set output: {exc}")

        try:
            hsp.write_hsp(path, body)
        except Exception as exc:  # noqa: BLE001
            return OpResult(ok=False, message=f"could not write tone: {exc}")

        return OpResult(ok=True, message="saved output")

    def set_bypass(self, tone_id: str, block: BlockVM, enabled: bool) -> OpResult:
        """Toggle one block's bypass/enable state in the library ``.hsp``,
        addressing it by the same ``(model, lane=@path, pos=@position)``
        coordinates ``save_params`` uses. An ambiguous target (same model at the
        same lane+pos across two DSP flows) raises ``MutateError``, surfaced as a
        failed op with no write — never a wrong-slot toggle. Atomic: builds the
        body in memory and only writes on full success."""
        path = self._hsp_path(tone_id)
        if not path:
            return OpResult(ok=False, message=f"{tone_id!r} has no library .hsp to edit")

        from helixgen import hsp, mutate

        try:
            body = hsp.read_hsp(path)
        except Exception as exc:  # noqa: BLE001 — surfaced to the footer
            return OpResult(ok=False, message=f"could not read tone: {exc}")

        lib = self._load_library()
        try:
            mutate.set_enabled(
                body,
                block.model,
                enabled,
                lib,
                lane=block.path,
                pos=block.position,
            )
        except Exception as exc:  # noqa: BLE001 — incl. the ambiguous-target refusal
            verb = "enable" if enabled else "bypass"
            return OpResult(ok=False, message=f"could not {verb} {block.model}: {exc}")

        try:
            hsp.write_hsp(path, body)
        except Exception as exc:  # noqa: BLE001
            return OpResult(ok=False, message=f"could not write tone: {exc}")

        return OpResult(ok=True, message="enabled block" if enabled else "bypassed block")

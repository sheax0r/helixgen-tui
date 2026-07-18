"""build_core(): the real Core wiring for the TUI.

Library and setlists are real adapters over the installed helixgen package;
the device port is a NullDevicePort placeholder until the real one lands in a
later task. Everything is offline local-file logic.
"""

from __future__ import annotations

import pathlib

from helixgen_tui.core.library import RealLibrary
from helixgen_tui.core.models import IrVM, MutationPlan, OpResult
from helixgen_tui.core.ports import Core, DeviceUnreachable
from helixgen_tui.core.setlists import RealSetlists

_PLACEHOLDER_MESSAGE = "device support arrives in a later task"


class NullDevicePort:
    """DevicePort stand-in: no device is wired up yet.

    probe() raises DeviceUnreachable("no device configured"); OpResult-typed
    methods return OpResult(ok=False, message="device support arrives in a
    later task"); plan/list/info methods return empty placeholders carrying
    the same message where they can.
    """

    def probe(self):
        raise DeviceUnreachable("no device configured")

    def _placeholder(self) -> OpResult:
        return OpResult(ok=False, message=_PLACEHOLDER_MESSAGE)

    def _placeholder_plan(self, title: str) -> MutationPlan:
        return MutationPlan(title=title, lines=(_PLACEHOLDER_MESSAGE,))

    def list_device_irs(self) -> list[IrVM]:
        return []

    def make_active(self, tone_id: str) -> OpResult:
        return self._placeholder()

    def sync_tone(self, tone_id: str) -> OpResult:
        return self._placeholder()

    def sync_setlist(self, name: str, gc: bool) -> OpResult:
        return self._placeholder()

    def plan_sync_all(self, gc: bool) -> MutationPlan:
        return self._placeholder_plan("Sync all")

    def sync_all(self, gc: bool) -> OpResult:
        return self._placeholder()

    def plan_delete_tone(self, tone_id: str) -> MutationPlan:
        return self._placeholder_plan("Delete tone")

    def delete_tone(self, tone_id: str) -> OpResult:
        return self._placeholder()

    def push_ir(self, ir_name: str) -> OpResult:
        return self._placeholder()

    def plan_delete_ir(self, ir_name: str) -> MutationPlan:
        return self._placeholder_plan("Delete IR")

    def delete_ir(self, ir_name: str) -> OpResult:
        return self._placeholder()

    def plan_prune_irs(self) -> MutationPlan:
        return self._placeholder_plan("Prune IRs")

    def prune_irs(self) -> OpResult:
        return self._placeholder()

    def rename_ir(self, ir_name: str, new_name: str) -> OpResult:
        return self._placeholder()

    def info(self) -> dict[str, str]:
        return {"status": _PLACEHOLDER_MESSAGE}

    def backup(self) -> OpResult:
        return self._placeholder()

    def plan_restore(self, file: str) -> MutationPlan:
        return self._placeholder_plan("Restore")

    def restore(self, file: str) -> OpResult:
        return self._placeholder()

    def lock_status(self) -> list[str]:
        return []


class RealCore:
    """Core over the local helixgen home; device port is a placeholder."""

    def __init__(self) -> None:
        self.library = RealLibrary()
        self.setlists = RealSetlists()
        self.device = NullDevicePort()

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

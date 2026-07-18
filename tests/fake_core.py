"""Scripted Core/DevicePort test doubles.

FakeCore implements the Core protocol entirely in memory so screens/tests can
be driven without a real helixgen library or a Line 6 Helix on the LAN.
FakeDevicePort additionally scripts offline, flake ("fail_next"), and
contention scenarios: it records every mutating call in `self.calls` and can
be told to raise DeviceUnreachable on its next call.
"""

from __future__ import annotations

from helixgen_tui.core.models import (
    ChainVM,
    DeviceStateVM,
    IrVM,
    MutationPlan,
    OpResult,
    ParamChange,
    SetlistVM,
    ToneVM,
)
from helixgen_tui.core.ports import DeviceUnreachable

_OFFLINE_STATE = DeviceStateVM(
    status="offline",
    model=None,
    address=None,
    active_tone=None,
    detail="device: ○ offline",
)


class FakeLibraryPort:
    """In-memory LibraryPort backed by a list of ToneVM given at construction."""

    def __init__(self, tones: list[ToneVM] | None = None) -> None:
        self.tones: list[ToneVM] = list(tones) if tones is not None else []

    def list_tones(self) -> list[ToneVM]:
        return list(self.tones)

    def get_tone(self, tone_id: str) -> ToneVM | None:
        for tone in self.tones:
            if tone.tone_id == tone_id:
                return tone
        return None


class FakeSetlistPort:
    """In-memory SetlistPort; mutations are recorded in `self.calls` AND applied
    to the stored setlists, so a subsequent `list_setlists()` reflects them —
    mirroring how `RealSetlists` persists to the manifest. (Without this, a
    screen's re-read on resume would wipe an optimistic membership echo.)"""

    def __init__(self, setlists: list[SetlistVM] | None = None) -> None:
        self.setlists: list[SetlistVM] = list(setlists) if setlists is not None else []
        self.calls: list[tuple[str, tuple]] = []

    def list_setlists(self) -> list[SetlistVM]:
        return list(self.setlists)

    def _replace_tones(self, setlist: str, tones: list[str]) -> None:
        for i, sl in enumerate(self.setlists):
            if sl.name == setlist:
                self.setlists[i] = SetlistVM(
                    name=sl.name, sync_enabled=sl.sync_enabled, tones=tuple(tones)
                )
                return

    def add_tone(self, setlist: str, tone_id: str) -> OpResult:
        self.calls.append(("add_tone", (setlist, tone_id)))
        for sl in self.setlists:
            if sl.name == setlist and tone_id not in sl.tones:
                self._replace_tones(setlist, [*sl.tones, tone_id])
                break
        return OpResult(True, "add_tone ok")

    def remove_tone(self, setlist: str, tone_id: str) -> OpResult:
        self.calls.append(("remove_tone", (setlist, tone_id)))
        for sl in self.setlists:
            if sl.name == setlist:
                self._replace_tones(setlist, [t for t in sl.tones if t != tone_id])
                break
        return OpResult(True, "remove_tone ok")

    def move_tone(self, setlist: str, tone_id: str, delta: int) -> OpResult:
        self.calls.append(("move_tone", (setlist, tone_id, delta)))
        for sl in self.setlists:
            if sl.name == setlist and tone_id in sl.tones:
                order = list(sl.tones)
                i = order.index(tone_id)
                j = i + delta
                if 0 <= j < len(order):
                    order[i], order[j] = order[j], order[i]
                    self._replace_tones(setlist, order)
                break
        return OpResult(True, "move_tone ok")


class FakeDevicePort:
    """Scripted DevicePort: records mutations, can be armed to raise once.

    `fail_next=True` (or setting `.fail_next = True` later) makes the very
    next call to any port method raise DeviceUnreachable; the flag then
    clears itself automatically so subsequent calls behave normally again.
    """

    def __init__(
        self,
        state: DeviceStateVM | None = None,
        fail_next: bool = False,
        device_irs: list[IrVM] | None = None,
    ) -> None:
        self.state: DeviceStateVM = state if state is not None else _OFFLINE_STATE
        self.fail_next = fail_next
        self.device_irs: list[IrVM] = list(device_irs) if device_irs is not None else []
        self.calls: list[tuple[str, tuple]] = []

    def _check_fail(self) -> None:
        if self.fail_next:
            self.fail_next = False
            raise DeviceUnreachable("fake device: scripted failure")

    def _mutate(self, verb: str, *args: object) -> OpResult:
        self._check_fail()
        self.calls.append((verb, args))
        return OpResult(True, f"{verb} ok")

    def probe(self) -> DeviceStateVM:
        self._check_fail()
        return self.state

    def list_device_irs(self) -> list[IrVM]:
        self._check_fail()
        return list(self.device_irs)

    def make_active(self, tone_id: str) -> OpResult:
        return self._mutate("make_active", tone_id)

    def sync_tone(self, tone_id: str) -> OpResult:
        return self._mutate("sync_tone", tone_id)

    def sync_setlist(self, name: str, gc: bool) -> OpResult:
        return self._mutate("sync_setlist", name, gc)

    def plan_sync_all(self, gc: bool) -> MutationPlan:
        self._check_fail()
        return MutationPlan(title="Sync all", lines=())

    def sync_all(self, gc: bool) -> OpResult:
        return self._mutate("sync_all", gc)

    def plan_delete_tone(self, tone_id: str) -> MutationPlan:
        self._check_fail()
        return MutationPlan(title="Delete tone", lines=(tone_id,))

    def delete_tone(self, tone_id: str) -> OpResult:
        return self._mutate("delete_tone", tone_id)

    def push_ir(self, ir_name: str) -> OpResult:
        return self._mutate("push_ir", ir_name)

    def plan_delete_ir(self, ir_name: str) -> MutationPlan:
        self._check_fail()
        return MutationPlan(title="Delete IR", lines=(ir_name,))

    def delete_ir(self, ir_name: str) -> OpResult:
        return self._mutate("delete_ir", ir_name)

    def plan_prune_irs(self) -> MutationPlan:
        self._check_fail()
        return MutationPlan(title="Prune IRs", lines=())

    def prune_irs(self) -> OpResult:
        return self._mutate("prune_irs")

    def rename_ir(self, ir_name: str, new_name: str) -> OpResult:
        return self._mutate("rename_ir", ir_name, new_name)

    def info(self) -> dict[str, str]:
        self._check_fail()
        return {}

    def backup(self) -> OpResult:
        return self._mutate("backup")

    def plan_restore(self, file: str) -> MutationPlan:
        self._check_fail()
        return MutationPlan(title="Restore", lines=(file,))

    def restore(self, file: str) -> OpResult:
        return self._mutate("restore", file)

    def lock_status(self) -> list[str]:
        self._check_fail()
        return []


class FakeEditorPort:
    """In-memory EditorPort: a dict of tone_id -> ChainVM, and a recorded log of
    every ``save_params`` call so screen tests can assert exactly what was
    written. ``save_params`` also rebases the stored chain's on-disk values to
    the saved values, mirroring how the real adapter persists — a subsequent
    ``get_chain`` reflects the save (and the screen's re-read comes back clean).
    """

    def __init__(self, chains: dict[str, ChainVM] | None = None) -> None:
        self.chains: dict[str, ChainVM] = dict(chains) if chains is not None else {}
        self.calls: list[tuple[str, list[ParamChange]]] = []
        self.fail_save: bool = False

    def get_chain(self, tone_id: str) -> ChainVM | None:
        return self.chains.get(tone_id)

    def save_params(self, tone_id: str, changes: list[ParamChange]) -> OpResult:
        self.calls.append((tone_id, list(changes)))
        if self.fail_save:
            return OpResult(ok=False, message="save failed (fake)")
        chain = self.chains.get(tone_id)
        if chain is not None:
            self.chains[tone_id] = _apply_changes(chain, changes)
        n = len(changes)
        return OpResult(ok=True, message=f"saved {n} change{'s' if n != 1 else ''}")


def _apply_changes(chain: ChainVM, changes: list[ParamChange]) -> ChainVM:
    """Return a copy of ``chain`` with each change's new value baked into the
    matching ParamVM (used by FakeEditorPort to rebase after a save)."""
    from helixgen_tui.core.models import BlockVM, ParamVM, PathVM

    index = {(c.model, c.path, c.position, c.param): c.value for c in changes}

    def _param(block: BlockVM, p: ParamVM) -> ParamVM:
        key = (block.model, block.path, block.position, p.name)
        if key in index:
            return ParamVM(name=p.name, value=index[key], type=p.type, default=p.default)
        return p

    new_paths = tuple(
        PathVM(
            path=path.path,
            blocks=tuple(
                BlockVM(
                    model=b.model,
                    display=b.display,
                    position=b.position,
                    path=b.path,
                    enabled=b.enabled,
                    params=tuple(_param(b, p) for p in b.params),
                )
                for b in path.blocks
            ),
        )
        for path in chain.paths
    )
    return ChainVM(
        tone_id=chain.tone_id,
        name=chain.name,
        guitar=chain.guitar,
        description=chain.description,
        setlists=chain.setlists,
        paths=new_paths,
        output=chain.output,
        input_source=chain.input_source,
    )


class FakeCore:
    """In-memory Core: all constructor args optional with empty-collection defaults."""

    def __init__(
        self,
        tones: list[ToneVM] | None = None,
        setlists: list[SetlistVM] | None = None,
        local_irs: list[IrVM] | None = None,
        device: FakeDevicePort | None = None,
        editor: FakeEditorPort | None = None,
        chains: dict[str, ChainVM] | None = None,
    ) -> None:
        self.library = FakeLibraryPort(tones)
        self.setlists = FakeSetlistPort(setlists)
        self.local_irs: list[IrVM] = list(local_irs) if local_irs is not None else []
        self.device: FakeDevicePort = device if device is not None else FakeDevicePort()
        self.editor: FakeEditorPort = (
            editor if editor is not None else FakeEditorPort(chains)
        )

    def list_local_irs(self) -> list[IrVM]:
        return list(self.local_irs)

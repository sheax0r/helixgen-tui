"""Scripted Core/DevicePort test doubles.

FakeCore implements the Core protocol entirely in memory so screens/tests can
be driven without a real helixgen library or a Line 6 Helix on the LAN.
FakeDevicePort additionally scripts offline, flake ("fail_next"), and
contention scenarios: it records every mutating call in `self.calls` and can
be told to raise DeviceUnreachable on its next call.
"""

from __future__ import annotations

from helixgen_tui.core.models import DeviceStateVM, IrVM, MutationPlan, OpResult, SetlistVM, ToneVM
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
    """In-memory SetlistPort; mutations are recorded in `self.calls`."""

    def __init__(self, setlists: list[SetlistVM] | None = None) -> None:
        self.setlists: list[SetlistVM] = list(setlists) if setlists is not None else []
        self.calls: list[tuple[str, tuple]] = []

    def list_setlists(self) -> list[SetlistVM]:
        return list(self.setlists)

    def add_tone(self, setlist: str, tone_id: str) -> OpResult:
        self.calls.append(("add_tone", (setlist, tone_id)))
        return OpResult(True, "add_tone ok")

    def remove_tone(self, setlist: str, tone_id: str) -> OpResult:
        self.calls.append(("remove_tone", (setlist, tone_id)))
        return OpResult(True, "remove_tone ok")

    def move_tone(self, setlist: str, tone_id: str, delta: int) -> OpResult:
        self.calls.append(("move_tone", (setlist, tone_id, delta)))
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


class FakeCore:
    """In-memory Core: all constructor args optional with empty-collection defaults."""

    def __init__(
        self,
        tones: list[ToneVM] | None = None,
        setlists: list[SetlistVM] | None = None,
        local_irs: list[IrVM] | None = None,
        device: FakeDevicePort | None = None,
    ) -> None:
        self.library = FakeLibraryPort(tones)
        self.setlists = FakeSetlistPort(setlists)
        self.local_irs: list[IrVM] = list(local_irs) if local_irs is not None else []
        self.device: FakeDevicePort = device if device is not None else FakeDevicePort()

    def list_local_irs(self) -> list[IrVM]:
        return list(self.local_irs)

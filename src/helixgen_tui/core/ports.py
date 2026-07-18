"""Port protocols the Textual screens depend on, and the Core they compose into.

All methods are synchronous — `DeviceService` (a later task) threads any
blocking device I/O off the UI event loop. Screens depend only on these
protocols, never on concrete helixgen types, so they can be driven by
`tests/fake_core.py` in isolation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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


@runtime_checkable
class LibraryPort(Protocol):
    def list_tones(self) -> list[ToneVM]: ...

    def get_tone(self, tone_id: str) -> ToneVM | None: ...


@runtime_checkable
class SetlistPort(Protocol):
    def list_setlists(self) -> list[SetlistVM]: ...

    def add_tone(self, setlist: str, tone_id: str) -> OpResult: ...

    def remove_tone(self, setlist: str, tone_id: str) -> OpResult: ...

    def move_tone(self, setlist: str, tone_id: str, delta: int) -> OpResult: ...


@runtime_checkable
class DevicePort(Protocol):
    def probe(self) -> DeviceStateVM:
        """Raises DeviceUnreachable on failure."""
        ...

    def list_device_irs(self) -> list[IrVM]: ...

    def make_active(self, tone_id: str) -> OpResult: ...

    def sync_tone(self, tone_id: str) -> OpResult: ...

    def sync_setlist(self, name: str, gc: bool) -> OpResult: ...

    def plan_sync_all(self, gc: bool) -> MutationPlan: ...

    def sync_all(self, gc: bool) -> OpResult: ...

    def plan_delete_tone(self, tone_id: str) -> MutationPlan: ...

    def delete_tone(self, tone_id: str) -> OpResult: ...

    def push_ir(self, ir_name: str) -> OpResult: ...

    def plan_delete_ir(self, ir_name: str) -> MutationPlan: ...

    def delete_ir(self, ir_name: str) -> OpResult: ...

    def plan_prune_irs(self) -> MutationPlan: ...

    def prune_irs(self) -> OpResult: ...

    def rename_ir(self, ir_name: str, new_name: str) -> OpResult: ...

    def info(self) -> dict[str, str]: ...

    def backup(self) -> OpResult: ...

    def plan_restore(self, file: str) -> MutationPlan: ...

    def restore(self, file: str) -> OpResult: ...

    def lock_status(self) -> list[str]: ...


@runtime_checkable
class EditorPort(Protocol):
    """Read a tone's editable signal chain, and write back changed params.

    ``get_chain`` returns the whole chain as view models (or ``None`` when the
    tone has no ``.hsp`` on disk — e.g. a device-origin tone); ``save_params``
    applies a batch of ``ParamChange`` edits to the library ``.hsp`` and returns
    an ``OpResult``. Neither touches the device.
    """

    def get_chain(self, tone_id: str) -> ChainVM | None: ...

    def save_params(self, tone_id: str, changes: list[ParamChange]) -> OpResult: ...

    def set_output(self, tone_id: str, level: float, pan: float) -> OpResult: ...


class DeviceUnreachable(Exception):
    """Raised by DevicePort methods when the device can't be reached."""


@runtime_checkable
class Core(Protocol):
    library: LibraryPort
    setlists: SetlistPort
    device: DevicePort
    editor: EditorPort

    def list_local_irs(self) -> list[IrVM]: ...

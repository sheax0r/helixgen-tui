"""IrsScreen: local/device IR panes, push, rename, delete, prune.

Left pane is a pure-local read (``Core.list_local_irs()``); the right pane
mirrors the device — an ``unavailable`` placeholder while offline, rows once
connected. Push (``p``) is instant-tier (no confirm); rename (``R``) is an
inline ``Input`` prompt; delete (``d``) and prune (``P``) show the port's
``MutationPlan`` in a ``ConfirmModal`` before running. Every mutation goes
through the app's ``DeviceService`` so offline refuses up front — no port
call, no modal/prompt — and reports why in the footer, same as the other
mode screens.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input, Static

from helixgen_tui.core.models import IrVM, OpResult
from helixgen_tui.core.ports import DeviceUnreachable
from helixgen_tui.screens.base import LibrarianScreen
from helixgen_tui.widgets.confirm_modal import ConfirmModal

_LOCAL_TABLE_ID = "irs-local-table"
_DEVICE_TABLE_ID = "irs-device-table"
_DEVICE_PLACEHOLDER_ID = "irs-device-placeholder"
_RENAME_INPUT_ID = "irs-rename-input"

_OFFLINE_MSG = "device offline — connect on the Device tab (4) first"
_DEVICE_PLACEHOLDER_TEXT = "unavailable — device offline"


def _short_hash(irhash: str | None) -> str:
    """First 8 hex chars of an IR hash — never the full hash, never a slot."""
    return irhash[:8] if irhash else ""


class IrsScreen(LibrarianScreen):
    """IRs-mode screen: local IR library (left) vs. device IRs (right)."""

    TAB_LABEL = "IRs"
    MODE_NAME = "irs"

    BINDINGS = [
        Binding("p", "push_ir", "Push"),
        Binding("R", "rename_ir", "Rename"),
        Binding("d", "delete_ir", "Delete"),
        Binding("P", "prune_irs", "Prune"),
        Binding("escape", "cancel_rename", "Cancel", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._local_irs: list[IrVM] = []
        self._device_irs: list[IrVM] = []
        self._renaming_ir: str | None = None

    def body(self) -> ComposeResult:
        with Horizontal():
            with Vertical():
                yield Static("Local IRs")
                yield DataTable(id=_LOCAL_TABLE_ID, cursor_type="row")
            with Vertical():
                yield Static("Device IRs")
                yield DataTable(id=_DEVICE_TABLE_ID, cursor_type="row")
                yield Static(_DEVICE_PLACEHOLDER_TEXT, id=_DEVICE_PLACEHOLDER_ID)
        yield Input(placeholder="rename IR", id=_RENAME_INPUT_ID)

    def on_mount(self) -> None:
        super().on_mount()  # seed the footer from the app's current device state
        local_table = self.query_one(f"#{_LOCAL_TABLE_ID}", DataTable)
        local_table.add_columns("Name", "Pack", "Hash")
        device_table = self.query_one(f"#{_DEVICE_TABLE_ID}", DataTable)
        device_table.add_columns("Name", "Pack", "Hash")
        self.query_one(f"#{_RENAME_INPUT_ID}", Input).display = False
        self.refresh_local_irs()
        self.refresh_device_pane()
        local_table.focus()

    # -- local pane ----------------------------------------------------------

    def refresh_local_irs(self) -> None:
        """Re-read the local IR list from core. A plain sync method (not a
        worker) — local reads are cheap, matching LibraryScreen.refresh_tones."""
        self._local_irs = self.app.core.list_local_irs()
        table = self.query_one(f"#{_LOCAL_TABLE_ID}", DataTable)
        table.clear()
        for ir in self._local_irs:
            table.add_row(ir.name, ir.pack or "", _short_hash(ir.irhash), key=ir.name)

    def _selected_local_ir(self) -> IrVM | None:
        table = self.query_one(f"#{_LOCAL_TABLE_ID}", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return next((ir for ir in self._local_irs if ir.name == row_key.value), None)

    # -- device pane -----------------------------------------------------------

    def refresh_device_pane(self) -> None:
        """Rebuild the device pane: the offline placeholder when not connected,
        or the device's IR rows once it is."""
        table = self.query_one(f"#{_DEVICE_TABLE_ID}", DataTable)
        placeholder = self.query_one(f"#{_DEVICE_PLACEHOLDER_ID}", Static)
        service = self.app.device_service
        if service is None or service.state.status != "connected":
            self._device_irs = []
            table.clear()
            table.display = False
            placeholder.display = True
            return
        try:
            self._device_irs = self.app.core.device.list_device_irs()
        except DeviceUnreachable:
            self._device_irs = []
            table.clear()
            table.display = False
            placeholder.display = True
            return
        table.clear()
        for ir in self._device_irs:
            table.add_row(ir.name, ir.pack or "", _short_hash(ir.irhash), key=ir.name)
        table.display = True
        placeholder.display = False

    def _selected_device_ir(self) -> IrVM | None:
        table = self.query_one(f"#{_DEVICE_TABLE_ID}", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return next((ir for ir in self._device_irs if ir.name == row_key.value), None)

    # -- offline guard ---------------------------------------------------------

    def _offline(self) -> bool:
        """True (and reports it to the footer) when no device is connected —
        the actions refuse here without ever touching the port."""
        service = self.app.device_service
        if service is None or service.state.status != "connected":
            self.app.report_op(OpResult(ok=False, message=_OFFLINE_MSG))
            return True
        return False

    def _after_mutation(self, result: OpResult) -> None:
        self.app.report_op(result)
        self.refresh_device_pane()

    # -- push (instant tier) ----------------------------------------------------

    def action_push_ir(self) -> None:
        if self._offline():
            return
        ir = self._selected_local_ir()
        if ir is None:
            return
        device = self.app.core.device
        ir_name = ir.name
        self.app.device_service.run(
            "push_ir", lambda: device.push_ir(ir_name), self._after_mutation
        )

    # -- delete (confirm) --------------------------------------------------

    def action_delete_ir(self) -> None:
        if self._offline():
            return
        ir = self._selected_device_ir()
        if ir is None:
            return
        plan = self.app.core.device.plan_delete_ir(ir.name)
        self.app.push_screen(ConfirmModal(plan), lambda ok: self._confirm_delete(ir.name, ok))

    def _confirm_delete(self, ir_name: str, confirmed: bool | None) -> None:
        if not confirmed:
            return
        device = self.app.core.device
        self.app.device_service.run(
            "delete_ir", lambda: device.delete_ir(ir_name), self._after_mutation
        )

    # -- prune (confirm) -----------------------------------------------------

    def action_prune_irs(self) -> None:
        if self._offline():
            return
        plan = self.app.core.device.plan_prune_irs()
        self.app.push_screen(ConfirmModal(plan), self._confirm_prune)

    def _confirm_prune(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        device = self.app.core.device
        self.app.device_service.run("prune_irs", lambda: device.prune_irs(), self._after_mutation)

    # -- rename (inline Input prompt) --------------------------------------

    def action_rename_ir(self) -> None:
        if self._offline():
            return
        ir = self._selected_device_ir()
        if ir is None:
            return
        self._renaming_ir = ir.name
        rename_input = self.query_one(f"#{_RENAME_INPUT_ID}", Input)
        rename_input.value = ir.name
        rename_input.display = True
        rename_input.focus()

    def action_cancel_rename(self) -> None:
        rename_input = self.query_one(f"#{_RENAME_INPUT_ID}", Input)
        if not rename_input.display:
            return
        rename_input.display = False
        self._renaming_ir = None
        self.query_one(f"#{_DEVICE_TABLE_ID}", DataTable).focus()

    @on(Input.Submitted, f"#{_RENAME_INPUT_ID}")
    def _on_rename_submitted(self, event: Input.Submitted) -> None:
        old_name = self._renaming_ir
        new_name = event.value.strip()
        rename_input = self.query_one(f"#{_RENAME_INPUT_ID}", Input)
        rename_input.display = False
        self._renaming_ir = None
        self.query_one(f"#{_DEVICE_TABLE_ID}", DataTable).focus()
        if not old_name or not new_name or new_name == old_name:
            return
        device = self.app.core.device
        self.app.device_service.run(
            "rename_ir",
            lambda: device.rename_ir(old_name, new_name),
            self._after_mutation,
        )

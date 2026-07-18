"""IrsScreen: local/device IR panes, push, rename, delete, prune.

Left pane is a pure-local read (``Core.list_local_irs()``); the right pane
mirrors the device — an ``unavailable`` placeholder while offline, rows once
connected. Push (``p``) is instant-tier (no confirm); rename (``R``) is an
inline ``Input`` prompt; delete (``d``) and prune (``P``) show the port's
``MutationPlan`` in a ``ConfirmModal`` before running.

Every device read/mutation goes through the app's ``DeviceService`` — ``run``
for mutations (``OpResult``), ``query`` for reads that return something else
(the device IR list, a ``MutationPlan``) — so offline refuses up front (no
port call), a wedged device call times out, and nothing here assumes a read
is I/O-free. ``run``/``query`` call their ``done`` callback off the UI
thread under the production thread-worker spawn, so any follow-up that
touches a widget or kicks off another device call hops back via
``post_message`` (mirroring ``screens/library.py``'s
``ActivateToneRequested``) rather than acting directly from the callback.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable, Input, Static

from helixgen_tui.core.device import QueryResult
from helixgen_tui.core.models import IrVM, MutationPlan, OpResult
from helixgen_tui.screens.base import LibrarianScreen
from helixgen_tui.widgets.confirm_modal import ConfirmModal

_LOCAL_TABLE_ID = "irs-local-table"
_DEVICE_TABLE_ID = "irs-device-table"
_DEVICE_PLACEHOLDER_ID = "irs-device-placeholder"
_RENAME_INPUT_ID = "irs-rename-input"

_DEVICE_PLACEHOLDER_TEXT = "unavailable — device offline"


def _short_hash(irhash: str | None) -> str:
    """First 8 hex chars of an IR hash — never the full hash, never a slot."""
    return irhash[:8] if irhash else ""


# Module-level Messages (not nested — see app.py's DeviceStateChanged for why):
# each is a UI-thread hand-off from a DeviceService `done` callback, which
# under the production thread-worker spawn runs off-thread, where touching
# widgets (or making another device call) directly would be unsafe.
class RefreshDeviceIrsRequested(Message):
    """Posted from a mutation's ``done`` callback: re-read the device IR list
    on the UI thread instead of refreshing synchronously from the worker."""


class DeviceIrsQueryReady(Message):
    """Posted from the ``list_device_irs`` query's ``done`` callback: rebuild
    the device table/placeholder on the UI thread."""

    def __init__(self, result: QueryResult) -> None:
        self.result = result
        super().__init__()


class DeleteIrPlanReady(Message):
    """Posted from the ``plan_delete_ir`` query's ``done`` callback: push the
    ConfirmModal on the UI thread once the plan arrives."""

    def __init__(self, ir_name: str, result: QueryResult) -> None:
        self.ir_name = ir_name
        self.result = result
        super().__init__()


class PruneIrsPlanReady(Message):
    """Posted from the ``plan_prune_irs`` query's ``done`` callback: push the
    ConfirmModal on the UI thread once the plan arrives."""

    def __init__(self, result: QueryResult) -> None:
        self.result = result
        super().__init__()


class IrsScreen(LibrarianScreen):
    """IRs-mode screen: local IR library (left) vs. device IRs (right)."""

    TAB_LABEL = "IRs"
    MODE_NAME = "irs"

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
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
        self.request_device_refresh()
        local_table.focus()

    # -- local pane (pure-local read; no device involved) -------------------

    def refresh_local_irs(self) -> None:
        """Re-read the local IR list from core. A plain sync method (not a
        worker) — local reads are cheap, matching LibraryScreen.refresh_tones."""
        self._local_irs = self.app.core.list_local_irs()
        table = self.query_one(f"#{_LOCAL_TABLE_ID}", DataTable)
        table.clear()
        # Row keys are list indices, not names: real libraries routinely hold
        # many IRs sharing one display name (mic/distance variants), and
        # DataTable raises DuplicateKey on a repeated key.
        for index, ir in enumerate(self._local_irs):
            table.add_row(ir.name, ir.pack or "", _short_hash(ir.irhash), key=str(index))

    def action_refresh(self) -> None:
        """`r`: re-read the local pane and re-query the device pane (matching
        LibraryScreen's refresh)."""
        self.refresh_local_irs()
        self.request_device_refresh()

    def on_screen_resume(self) -> None:
        """Refresh both panes on every return to this (singleton) mode screen —
        on_mount fires once, so IRs registered/pushed elsewhere would otherwise
        stay stale. The device pane refreshes via the existing query path."""
        self.refresh_local_irs()
        self.request_device_refresh()

    def _selected_local_ir(self) -> IrVM | None:
        table = self.query_one(f"#{_LOCAL_TABLE_ID}", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return self._local_irs[int(row_key.value)]

    # -- device pane (async: DeviceService.query, never a direct port call) --

    def request_device_refresh(self) -> None:
        """Kick off an async device-IR read. UI-thread only: called from
        on_mount, and from the RefreshDeviceIrsRequested handler after a
        mutation. `DeviceService.query` itself handles the offline
        short-circuit (delivered synchronously in that case, off-thread
        otherwise) — either way the result reaches `_apply_device_irs` only
        via `on_device_irs_query_ready`, so the table is only ever touched
        from the UI thread."""
        service = self.app.device_service
        if service is None:
            self._apply_device_irs(QueryResult(ok=False, value=None, message="device offline"))
            return
        device = self.app.core.device
        service.query("list_device_irs", device.list_device_irs, self._on_device_irs_query_done)

    def _on_device_irs_query_done(self, result: QueryResult) -> None:
        self.post_message(DeviceIrsQueryReady(result))

    def on_device_irs_query_ready(self, message: DeviceIrsQueryReady) -> None:
        self._apply_device_irs(message.result)

    def on_refresh_device_irs_requested(self, message: RefreshDeviceIrsRequested) -> None:
        self.request_device_refresh()

    def _apply_device_irs(self, result: QueryResult) -> None:
        table = self.query_one(f"#{_DEVICE_TABLE_ID}", DataTable)
        placeholder = self.query_one(f"#{_DEVICE_PLACEHOLDER_ID}", Static)
        if not result.ok or result.value is None:
            self._device_irs = []
            table.clear()
            table.display = False
            placeholder.display = True
            return
        self._device_irs = list(result.value)  # type: ignore[arg-type]
        table.clear()
        for index, ir in enumerate(self._device_irs):
            table.add_row(ir.name, ir.pack or "", _short_hash(ir.irhash), key=str(index))
        table.display = True
        placeholder.display = False

    def _selected_device_ir(self) -> IrVM | None:
        table = self.query_one(f"#{_DEVICE_TABLE_ID}", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return self._device_irs[int(row_key.value)]

    # -- offline guard is inherited from LibrarianScreen._offline ----------

    def _after_mutation(self, result: OpResult) -> None:
        """`DeviceService.run`'s done callback for push/delete/prune/rename —
        runs off the UI thread under the production spawn. `report_op` is
        thread-safe on its own (posts a message internally); the device-pane
        refresh is not (it touches widgets and would otherwise be a second
        synchronous device read), so it's requested via post_message instead
        of called directly."""
        self.app.report_op(result)
        self.post_message(RefreshDeviceIrsRequested())

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
        device = self.app.core.device
        ir_name = ir.name
        self.app.device_service.query(
            "plan_delete_ir",
            lambda: device.plan_delete_ir(ir_name),
            lambda result: self.post_message(DeleteIrPlanReady(ir_name, result)),
        )

    def on_delete_ir_plan_ready(self, message: DeleteIrPlanReady) -> None:
        if not message.result.ok or message.result.value is None:
            self.app.report_op(
                OpResult(
                    ok=False,
                    message=message.result.message or "could not load delete plan",
                )
            )
            return
        plan: MutationPlan = message.result.value  # type: ignore[assignment]
        self.app.push_screen(
            ConfirmModal(plan), lambda ok: self._confirm_delete(message.ir_name, ok)
        )

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
        device = self.app.core.device
        self.app.device_service.query(
            "plan_prune_irs",
            device.plan_prune_irs,
            lambda result: self.post_message(PruneIrsPlanReady(result)),
        )

    def on_prune_irs_plan_ready(self, message: PruneIrsPlanReady) -> None:
        if not message.result.ok or message.result.value is None:
            self.app.report_op(
                OpResult(
                    ok=False,
                    message=message.result.message or "could not load prune plan",
                )
            )
            return
        plan: MutationPlan = message.result.value  # type: ignore[assignment]
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

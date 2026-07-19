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

from typing import Callable, Sequence

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import DataTable, Input, Static

from helixgen_tui.core.device import QueryResult
from helixgen_tui.core.models import IrVM, MutationPlan, OpResult
from helixgen_tui.screens.base import LibrarianScreen
from helixgen_tui.screens.filterable import FilterableTableMixin
from helixgen_tui.widgets.confirm_modal import ConfirmModal

_LOCAL_TABLE_ID = "irs-local-table"
_DEVICE_TABLE_ID = "irs-device-table"
_DEVICE_PLACEHOLDER_ID = "irs-device-placeholder"
_RENAME_INPUT_ID = "irs-rename-input"
_FILTER_ID = "irs-filter"

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


class _IrPane(FilterableTableMixin):
    """One filterable IR pane.

    ``FilterableTableMixin`` wires one Input to one DataTable, and this screen
    has two tables sharing a single filter — so each pane gets its own small
    host that delegates widget lookup back to the screen. ``active`` is the
    focused-pane flag: an inactive pane reports an empty query, which is what
    restores it to native order when focus moves to the other side.
    """

    def __init__(
        self, screen: LibrarianScreen, table_id: str, items: Callable[[], list[IrVM]]
    ) -> None:
        self._screen = screen
        self._items = items
        self.filter_input_id = _FILTER_ID
        self.filter_table_id = table_id
        self.active = False
        # Row keys stay positional (IR display names routinely duplicate, and
        # DataTable rejects a repeated key) but nothing derives a backing index
        # from them any more — selection resolves through the mixin's _visible.
        self._keys: dict[int, str] = {}
        super().__init__()

    def query_one(self, selector, expect_type=None):  # type: ignore[no-untyped-def]
        return self._screen.query_one(selector, expect_type)

    def filter_query(self) -> str:
        return super().filter_query() if self.active else ""

    def filter_items(self) -> Sequence[IrVM]:
        items = self._items()
        self._keys = {id(ir): str(position) for position, ir in enumerate(items)}
        return items

    def filter_text(self, item: IrVM) -> str:
        return item.name

    def filter_row(self, item: IrVM, label: Text) -> tuple[object, ...]:
        return (label, Text(item.pack or ""), _short_hash(item.irhash))

    def filter_row_key(self, item: IrVM) -> str | None:
        return self._keys.get(id(item))

    def filter_on_enter(self, item: IrVM) -> None:
        """Enter in the filter parks the cursor on the best match and stops
        there. Push/delete/rename/prune stay on ``p``/``d``/``R``/``P``: no
        device write is ever a side effect of searching."""
        self.move_cursor_to(item)


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
        Binding("slash", "focus_filter", "Filter", key_display="/"),
        Binding("escape", "cancel_rename", "Cancel", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._local_irs: list[IrVM] = []
        self._device_irs: list[IrVM] = []
        self._renaming_ir: str | None = None
        self._local_pane = _IrPane(self, _LOCAL_TABLE_ID, lambda: self._local_irs)
        self._device_pane = _IrPane(self, _DEVICE_TABLE_ID, lambda: self._device_irs)
        self._local_pane.active = True

    def body(self) -> ComposeResult:
        yield Input(placeholder="filter", id=_FILTER_ID)
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
        self._local_pane.rebuild_filtered()

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
        """Resolved through the pane's visible list, never by mapping a row key
        back into ``_local_irs`` — a filtered pane's rows no longer line up with
        backing-list positions."""
        return self._local_pane.selected()

    # -- the shared filter (applies to whichever pane holds focus) ----------

    def action_focus_filter(self) -> None:
        self.query_one(f"#{_FILTER_ID}", Input).focus()

    def _rebuild_panes(self) -> None:
        self._local_pane.rebuild_filtered()
        if self.query_one(f"#{_DEVICE_TABLE_ID}", DataTable).display:
            self._device_pane.rebuild_filtered()

    @on(Input.Changed, f"#{_FILTER_ID}")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self._rebuild_panes()

    @on(Input.Submitted, f"#{_FILTER_ID}")
    def _on_filter_submitted(self, event: Input.Submitted) -> None:
        self._active_pane().handle_filter_submitted()

    def _active_pane(self) -> _IrPane:
        return self._device_pane if self._device_pane.active else self._local_pane

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Focusing a pane hands it the filter: the query re-applies to the
        newly focused table and the other one falls back to native order.
        Focusing the filter Input itself changes nothing — the pane the user
        came from stays the target."""
        pane = {_LOCAL_TABLE_ID: self._local_pane, _DEVICE_TABLE_ID: self._device_pane}.get(
            event.widget.id or ""
        )
        if pane is None or pane.active:
            return
        self._local_pane.active = pane is self._local_pane
        self._device_pane.active = pane is self._device_pane
        self._rebuild_panes()

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
            self._device_pane.rebuild_filtered()
            table.display = False
            placeholder.display = True
            return
        self._device_irs = list(result.value)  # type: ignore[arg-type]
        self._device_pane.rebuild_filtered()
        table.display = True
        placeholder.display = False

    def _selected_device_ir(self) -> IrVM | None:
        """Resolved through the pane's visible list — see _selected_local_ir."""
        return self._device_pane.selected()

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
        # Push by irhash, not display name: names are routinely duplicated
        # (see refresh_local_irs), and core resolves an exact hash key first.
        ir_ref = ir.irhash or ir.name
        self.app.device_service.run(
            "push_ir", lambda: device.push_ir(ir_ref), self._after_mutation
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
        """Escape unwinds one step at a time: drop a live filter query first,
        and only then cancel an open rename prompt."""
        filter_input = self.query_one(f"#{_FILTER_ID}", Input)
        if filter_input.value:
            filter_input.value = ""  # triggers Input.Changed -> rebuild
            return
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

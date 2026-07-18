"""DeviceScreen: device info, backup, restore, lock status, and retry-connect.

All actions read the app's single ``DeviceService`` state directly (never a
port call) to decide whether to refuse offline, mirroring the other mode
screens. ``info``/``lock_status`` are read-only device queries — like every
other device read in this app they go through ``DeviceService.query`` rather
than calling the port directly, so a slow/wedged device times out instead of
blocking the UI thread and a connect/drop race can't raise
``DeviceUnreachable`` unhandled. ``backup`` is an instant-tier mutating action
(fires straight through ``DeviceService.run``); ``restore`` is a destructive
one, gated by a path prompt, then a query for the port's ``plan_restore``
plan, then a ``ConfirmModal`` opened once that plan arrives.

``query``'s ``done`` callback runs off the UI thread under the production
thread-worker spawn (see ``core/device.py``), so every follow-up that touches
a widget or opens a modal hops back via ``post_message`` — mirroring
``screens/irs.py``'s module-level ``*Ready`` messages — rather than acting
directly from the callback.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from helixgen_tui.core.device import QueryResult
from helixgen_tui.core.models import MutationPlan, OpResult
from helixgen_tui.screens.base import LibrarianScreen
from helixgen_tui.widgets.confirm_modal import ConfirmModal

_INFO_ID = "device-info"
_LOCKS_ID = "device-locks"
_RESTORE_INPUT_ID = "device-restore-path"

_OFFLINE_INFO = "device offline — no info available. Press r to retry."
_OFFLINE_REFUSAL = "device offline — press r to retry"


class RestorePathModal(ModalScreen[str | None]):
    """Prompts for a backup file path; Enter submits, escape cancels."""

    DEFAULT_CSS = """
    RestorePathModal {
        align: center middle;
    }

    RestorePathModal > Container {
        width: auto;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $panel;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Restore from file (enter path, then Enter):")
            yield Input(placeholder="/path/to/backup.hlx", id=_RESTORE_INPUT_ID)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted, f"#{_RESTORE_INPUT_ID}")
    def _submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# Module-level Messages (not nested — see app.py's DeviceStateChanged for why):
# each is a UI-thread hand-off from a DeviceService `done` callback, which
# under the production thread-worker spawn runs off-thread, where touching
# widgets (or making another device call) directly would be unsafe.
class InfoQueryReady(Message):
    """Posted from the ``info`` query's ``done`` callback: render the info
    panel on the UI thread once the payload arrives."""

    def __init__(self, result: QueryResult) -> None:
        self.result = result
        super().__init__()


class LocksQueryReady(Message):
    """Posted from the ``lock_status`` query's ``done`` callback: render the
    locks panel on the UI thread once the payload arrives."""

    def __init__(self, result: QueryResult) -> None:
        self.result = result
        super().__init__()


class RestorePlanReady(Message):
    """Posted from the ``plan_restore`` query's ``done`` callback: push the
    ConfirmModal on the UI thread once the plan arrives."""

    def __init__(self, path: str, result: QueryResult) -> None:
        self.path = path
        self.result = result
        super().__init__()


class DeviceScreen(LibrarianScreen):
    """Device-mode screen: info table, active tone, backup/restore, locks, retry."""

    TAB_LABEL = "Device"
    MODE_NAME = "device"

    BINDINGS = [
        Binding("b", "backup", "Backup"),
        Binding("t", "restore", "Restore"),
        Binding("l", "show_locks", "Locks"),
        Binding("r", "retry", "Retry"),
    ]

    def body(self) -> ComposeResult:
        yield Static("", id=_INFO_ID)
        yield Static("", id=_LOCKS_ID)

    def on_mount(self) -> None:
        super().on_mount()  # seed the footer from the app's current device state
        self._refresh_info()

    def on_screen_resume(self) -> None:
        """Re-read device info on every return to this (singleton) mode screen —
        on_mount fires once, so a state/info change while another tab was active
        would otherwise leave a stale panel."""
        self._refresh_info()

    # -- state helpers -------------------------------------------------------

    def _connected(self) -> bool:
        service = self.app.device_service
        return service is not None and service.state.status == "connected"

    def _refuse_offline(self) -> bool:
        """True (and reports it to the footer) when offline — actions refuse
        here without ever touching the port."""
        return self._offline(_OFFLINE_REFUSAL)

    # -- info (async query) ---------------------------------------------------

    def _refresh_info(self) -> None:
        """Kick off an async ``info`` read when connected; otherwise render the
        offline placeholder immediately (no port call). UI-thread only: called
        from on_mount and the `r` retry action. `DeviceService.query` handles
        its own offline short-circuit and any connect/drop race — either way
        the result reaches `_apply_info` only via `on_info_query_ready`, so
        the widget is only ever touched from the UI thread."""
        if not self._connected():
            self._apply_info(QueryResult(ok=False, value=None, message="device offline"))
            self.query_one(f"#{_LOCKS_ID}", Static).update("")
            return
        device = self.app.core.device
        self.app.device_service.query("info", device.info, self._on_info_query_done)

    def _on_info_query_done(self, result: QueryResult) -> None:
        self.post_message(InfoQueryReady(result))

    def on_info_query_ready(self, message: InfoQueryReady) -> None:
        self._apply_info(message.result)

    def _apply_info(self, result: QueryResult) -> None:
        info_widget = self.query_one(f"#{_INFO_ID}", Static)
        if not result.ok or result.value is None:
            info_widget.update(_OFFLINE_INFO)
            return
        info: dict = result.value  # type: ignore[assignment]
        state = self.app.device_service.state
        lines = [f"{key}: {value}" for key, value in info.items()]
        lines.append(f"Active tone: {state.active_tone or '—'}")
        info_widget.update("\n".join(lines))

    # -- locks (async query) ---------------------------------------------------

    def _refresh_locks(self) -> None:
        """Kick off an async ``lock_status`` read. Only ever called after the
        `l` action's offline gate, but the query re-checks connectivity itself
        so a connect/drop race between the gate and the read still resolves to
        the offline empty state instead of touching the port."""
        device = self.app.core.device
        self.app.device_service.query("lock_status", device.lock_status, self._on_locks_query_done)

    def _on_locks_query_done(self, result: QueryResult) -> None:
        self.post_message(LocksQueryReady(result))

    def on_locks_query_ready(self, message: LocksQueryReady) -> None:
        self._apply_locks(message.result)

    def _apply_locks(self, result: QueryResult) -> None:
        locks_widget = self.query_one(f"#{_LOCKS_ID}", Static)
        if not result.ok or result.value is None:
            locks_widget.update("")
            return
        locks = list(result.value)  # type: ignore[arg-type]
        locks_widget.update("\n".join(locks) if locks else "locks: none")

    # -- actions -------------------------------------------------------------

    def action_retry(self) -> None:
        service = self.app.device_service
        if service is not None:
            service.retry_now()
        self._refresh_info()

    def action_show_locks(self) -> None:
        if self._refuse_offline():
            return
        self._refresh_locks()

    def action_backup(self) -> None:
        if self._refuse_offline():
            return
        device = self.app.core.device
        self.app.device_service.run("backup", device.backup, self.app.report_op)

    def action_restore(self) -> None:
        if self._refuse_offline():
            return
        self.app.push_screen(RestorePathModal(), self._on_restore_path)

    def _on_restore_path(self, path: str | None) -> None:
        if not path:
            return
        device = self.app.core.device
        self.app.device_service.query(
            "plan_restore",
            lambda: device.plan_restore(path),
            lambda result: self.post_message(RestorePlanReady(path, result)),
        )

    def on_restore_plan_ready(self, message: RestorePlanReady) -> None:
        if not message.result.ok or message.result.value is None:
            self.app.report_op(
                OpResult(
                    ok=False,
                    message=message.result.message or "could not load restore plan",
                )
            )
            return
        plan: MutationPlan = message.result.value  # type: ignore[assignment]
        self.app.push_screen(ConfirmModal(plan), lambda ok: self._do_restore(message.path, ok))

    def _do_restore(self, path: str, confirmed: bool | None) -> None:
        if not confirmed:
            return
        device = self.app.core.device
        self.app.device_service.run("restore", lambda: device.restore(path), self.app.report_op)

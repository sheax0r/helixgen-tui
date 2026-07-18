"""DeviceScreen: device info, backup, restore, lock status, and retry-connect.

All actions read the app's single ``DeviceService`` state directly (never a
port call) to decide whether to refuse offline, mirroring the other mode
screens. ``info``/``lock_status`` are read-only device queries so they're
only ever attempted while connected; ``backup`` is an instant-tier mutating
action (fires straight through ``DeviceService.run``); ``restore`` is a
destructive one, gated by a path prompt then a ``ConfirmModal`` showing the
port's ``plan_restore`` plan.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from helixgen_tui.core.models import OpResult
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

    # -- state helpers -------------------------------------------------------

    def _connected(self) -> bool:
        service = self.app.device_service
        return service is not None and service.state.status == "connected"

    def _refuse_offline(self) -> bool:
        """True (and reports it to the footer) when offline — actions refuse
        here without ever touching the port."""
        if self._connected():
            return False
        self.app.report_op(OpResult(ok=False, message=_OFFLINE_REFUSAL))
        return True

    # -- rendering -------------------------------------------------------------

    def _refresh_info(self) -> None:
        info_widget = self.query_one(f"#{_INFO_ID}", Static)
        if not self._connected():
            info_widget.update(_OFFLINE_INFO)
            self.query_one(f"#{_LOCKS_ID}", Static).update("")
            return
        device = self.app.core.device
        info = device.info()
        state = self.app.device_service.state
        lines = [f"{key}: {value}" for key, value in info.items()]
        lines.append(f"Active tone: {state.active_tone or '—'}")
        info_widget.update("\n".join(lines))

    def _refresh_locks(self) -> None:
        locks_widget = self.query_one(f"#{_LOCKS_ID}", Static)
        if not self._connected():
            locks_widget.update("")
            return
        locks = self.app.core.device.lock_status()
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
        plan = device.plan_restore(path)
        self.app.push_screen(ConfirmModal(plan), lambda ok: self._do_restore(path, ok))

    def _do_restore(self, path: str, confirmed: bool | None) -> None:
        if not confirmed:
            return
        device = self.app.core.device
        self.app.device_service.run("restore", lambda: device.restore(path), self.app.report_op)

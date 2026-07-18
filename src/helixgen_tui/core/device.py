"""DeviceService: offline-first device lifecycle around a DevicePort.

Owns the app's single view of device connectivity. Probing the port reports a
``DeviceStateVM`` through ``on_state``; mutating work goes through ``run``,
which short-circuits when offline (never touching the port), enforces a
timeout, and flips the service offline the moment the port raises
``DeviceUnreachable``.

Blocking I/O is handed to ``spawn``. The default is a daemon-thread runner; the
app upgrades it to a Textual thread-worker so callbacks ride the event loop, and
tests inject a synchronous ``spawn`` so every path runs inline and
deterministically. ``start`` fires the first probe to begin the cycle; the
owner re-probes on its own cadence (``poll_interval``) via ``retry_now`` — kept
off DeviceService so a sleeping thread never blocks a synchronous ``spawn``.
``run`` runs ``fn`` in its own thread and joins with ``timeout`` — so a wedged
device call becomes ``ok=False`` "timed out" instead of blocking forever, even
under a synchronous ``spawn``.
"""

from __future__ import annotations

import threading
from typing import Callable

from helixgen_tui.core.models import DeviceStateVM, OpResult
from helixgen_tui.core.ports import DevicePort, DeviceUnreachable

_OFFLINE = DeviceStateVM(
    status="offline",
    model=None,
    address=None,
    active_tone=None,
    detail="device: ○ offline",
)


def _default_spawn(fn: Callable[[], None]) -> None:
    """Run ``fn`` on a daemon thread — the standalone default when no app-owned
    Textual worker spawn is injected."""
    threading.Thread(target=fn, daemon=True).start()


class DeviceService:
    def __init__(
        self,
        port: DevicePort,
        on_state: Callable[[DeviceStateVM], None],
        poll_interval: float = 15.0,
        timeout: float = 5.0,
        spawn: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._port = port
        self._on_state = on_state
        self.poll_interval = poll_interval
        self._timeout = timeout
        self._spawn = spawn if spawn is not None else _default_spawn
        self._state = _OFFLINE

    @property
    def state(self) -> DeviceStateVM:
        return self._state

    def start(self) -> None:
        """Begin the probe cycle: fire the first probe off-thread. The owner
        keeps the cycle going by calling ``retry_now`` on ``poll_interval``."""
        self._spawn(self._probe_once)

    def retry_now(self) -> None:
        """Probe once, off-thread, updating state/``on_state`` with the result."""
        self._spawn(self._probe_once)

    def run(
        self,
        label: str,
        fn: Callable[[], OpResult],
        done: Callable[[OpResult], None],
    ) -> None:
        """Run ``fn`` off-thread with a timeout, delivering an ``OpResult`` to
        ``done``. Offline short-circuits to ``OpResult(ok=False, "device
        offline")`` without calling ``fn``; ``DeviceUnreachable`` flips the
        service offline; exceeding ``timeout`` yields ``ok=False`` "timed out".
        """
        if self._state.status == "offline":
            done(OpResult(ok=False, message="device offline"))
            return
        self._spawn(lambda: self._run_guarded(label, fn, done))

    # -- internals ---------------------------------------------------------

    def _probe_once(self) -> None:
        try:
            state = self._port.probe()
        except DeviceUnreachable:
            self._set_state(_OFFLINE)
            return
        self._set_state(state)

    def _set_state(self, state: DeviceStateVM) -> None:
        self._state = state
        self._on_state(state)

    def _run_guarded(
        self,
        label: str,
        fn: Callable[[], OpResult],
        done: Callable[[OpResult], None],
    ) -> None:
        box: dict[str, object] = {}

        def _target() -> None:
            try:
                box["result"] = fn()
            except DeviceUnreachable as exc:
                box["unreachable"] = exc
            except Exception as exc:  # noqa: BLE001 — surfaced as ok=False below
                box["error"] = exc

        worker = threading.Thread(target=_target, daemon=True)
        worker.start()
        worker.join(self._timeout)

        if worker.is_alive():
            done(OpResult(ok=False, message=f"{label}: timed out"))
            return
        if "unreachable" in box:
            self._set_state(_OFFLINE)
            done(OpResult(ok=False, message="device offline"))
            return
        if "error" in box:
            done(OpResult(ok=False, message=f"{label}: {box['error']}"))
            return
        done(box["result"])  # type: ignore[arg-type]

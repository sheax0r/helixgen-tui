"""DeviceService: offline-first device lifecycle around a DevicePort.

Owns the app's single view of device connectivity. Probing the port reports a
``DeviceStateVM`` through ``on_state``; mutating work goes through ``run``,
which short-circuits when offline (never touching the port), enforces a
timeout, and flips the service offline the moment the port raises
``DeviceUnreachable``. Reads that return an arbitrary value (not an
``OpResult``) go through ``query`` — same offline/timeout/unreachable
discipline as ``run``, but delivering a ``QueryResult`` so callers can react
to the value on success or the message on failure.

Blocking I/O is handed to ``spawn``. The default is a daemon-thread runner; the
app upgrades it to a Textual thread-worker so callbacks ride the event loop, and
tests inject a synchronous ``spawn`` so every path runs inline and
deterministically. ``start`` fires the first probe to begin the cycle; the
owner re-probes on its own cadence (``poll_interval``) via ``retry_now`` — kept
off DeviceService so a sleeping thread never blocks a synchronous ``spawn``.
``run``/``query`` run ``fn`` in its own thread and join with ``timeout`` — so a
wedged device call becomes a "timed out" failure instead of blocking forever,
even under a synchronous ``spawn``.

Both ``run`` and ``query`` deliver their result via ``done`` off the caller's
thread whenever the read/mutation actually executes (i.e. not offline) —
callers that touch UI widgets from ``done`` must hop back to the UI thread
themselves (``post_message``; see ``screens/library.py``'s
``ActivateToneRequested`` and ``screens/irs.py``'s equivalent messages).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Result of a ``DeviceService.query()`` read.

    ``ok`` and ``value`` on success; ``ok=False`` and ``message`` explaining
    why (offline, unreachable, timed out, or the read raised) otherwise.
    ``value`` is untyped (``object``) since queries can return any shape —
    a tone list, an IR list, a ``MutationPlan``, ... — callers know what
    they asked for.
    """

    ok: bool
    value: object | None
    message: str


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

    def query(
        self,
        label: str,
        fn: Callable[[], object],
        done: Callable[[QueryResult], None],
    ) -> None:
        """Run a read ``fn`` off-thread with a timeout, delivering a
        ``QueryResult`` to ``done``. Same discipline as ``run``: offline
        short-circuits to ``QueryResult(ok=False, ...)`` without calling
        ``fn``; ``DeviceUnreachable`` flips the service offline; exceeding
        ``timeout`` yields a failure. Use this instead of calling a
        ``DevicePort`` read directly whenever the caller can't guarantee the
        read is free of I/O (list_device_irs, plan_* methods, ...).
        """
        if self._state.status == "offline":
            done(QueryResult(ok=False, value=None, message="device offline"))
            return
        self._spawn(lambda: self._query_guarded(label, fn, done))

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

    def _call_guarded(self, fn: Callable[[], object]) -> tuple[str, object]:
        """Run ``fn`` on a joined thread with the service timeout.

        Returns ``("ok", value)``, ``("timeout", None)``,
        ``("unreachable", exc)``, or ``("error", exc)`` — the shared
        timeout/exception plumbing behind both ``run`` and ``query``.
        """
        box: dict[str, object] = {}

        def _target() -> None:
            try:
                box["value"] = fn()
            except DeviceUnreachable as exc:
                box["unreachable"] = exc
            except Exception as exc:  # noqa: BLE001 — surfaced by the caller
                box["error"] = exc

        worker = threading.Thread(target=_target, daemon=True)
        worker.start()
        worker.join(self._timeout)

        if worker.is_alive():
            return "timeout", None
        if "unreachable" in box:
            return "unreachable", box["unreachable"]
        if "error" in box:
            return "error", box["error"]
        return "ok", box["value"]

    def _run_guarded(
        self,
        label: str,
        fn: Callable[[], OpResult],
        done: Callable[[OpResult], None],
    ) -> None:
        status, payload = self._call_guarded(fn)
        if status == "timeout":
            done(OpResult(ok=False, message=f"{label}: timed out"))
        elif status == "unreachable":
            self._set_state(_OFFLINE)
            done(OpResult(ok=False, message="device offline"))
        elif status == "error":
            done(OpResult(ok=False, message=f"{label}: {payload}"))
        else:
            done(payload)  # type: ignore[arg-type]

    def _query_guarded(
        self,
        label: str,
        fn: Callable[[], object],
        done: Callable[[QueryResult], None],
    ) -> None:
        status, payload = self._call_guarded(fn)
        if status == "timeout":
            done(QueryResult(ok=False, value=None, message=f"{label}: timed out"))
        elif status == "unreachable":
            self._set_state(_OFFLINE)
            done(QueryResult(ok=False, value=None, message="device offline"))
        elif status == "error":
            done(QueryResult(ok=False, value=None, message=f"{label}: {payload}"))
        else:
            done(QueryResult(ok=True, value=payload, message=""))

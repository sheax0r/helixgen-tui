"""Frozen view models handed from Core ports to Textual screens.

These are pure data: no behavior, no helixgen imports. Every dataclass is
`frozen=True, slots=True` so screens can't accidentally mutate what they
render, and equality/hashing fall out for free in tests.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class SyncState(enum.Enum):
    """Whether a tone is present on the device, only local, or unknown (offline)."""

    SYNCED = "synced"
    LOCAL_ONLY = "local"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToneVM:
    name: str
    tone_id: str
    guitar: str | None
    description: str | None
    sync: SyncState
    setlists: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SetlistVM:
    name: str
    sync_enabled: bool
    tones: tuple[str, ...]  # tone ids, in order (currently equal to names for RealLibrary)


@dataclass(frozen=True, slots=True)
class IrVM:
    name: str
    pack: str | None
    irhash: str | None
    on_device: bool | None  # None = unknown/offline


@dataclass(frozen=True, slots=True)
class DeviceStateVM:
    # status in {"offline", "connecting", "connected"}
    status: str
    model: str | None
    address: str | None
    active_tone: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class MutationPlan:
    """What a confirm modal displays before a destructive/mutating action runs."""

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OpResult:
    ok: bool
    message: str


# --- tone param editor (v0.2.0) ---------------------------------------------
#
# UI-facing view of a tone's signal chain and its editable params. Framework-
# free like everything else here: the editor screen renders these and hands
# ``ParamChange`` records back to ``EditorPort.save_params``.

ParamValue = float | int | bool | str


@dataclass(frozen=True, slots=True)
class ParamVM:
    """One editable param on a block: its name, current value, declared type
    (``"float"``/``"int"``/``"bool"``/``"str"``), and schema default (``None``
    when the block/param isn't catalogued in the library)."""

    name: str
    value: ParamValue
    type: str
    default: ParamValue | None


@dataclass(frozen=True, slots=True)
class BlockVM:
    """One block in the chain. ``model`` is the raw ``@model`` id (what
    ``mutate.set_param`` matches on); ``display`` is a human label; ``path`` is
    the parallel lane (raw ``@path``) and ``position`` the slot pos (raw
    ``@position``) — together they address the slot for a write."""

    model: str
    display: str
    position: int
    path: int
    enabled: bool
    params: tuple[ParamVM, ...]


@dataclass(frozen=True, slots=True)
class PathVM:
    """A parallel lane of the chain: its ``path`` index and its blocks in order."""

    path: int
    blocks: tuple[BlockVM, ...]


@dataclass(frozen=True, slots=True)
class ChainVM:
    """A tone's full editable chain plus the header metadata the editor shows."""

    tone_id: str
    name: str
    guitar: str | None
    description: str | None
    setlists: tuple[str, ...]
    paths: tuple[PathVM, ...]


@dataclass(frozen=True, slots=True)
class ParamChange:
    """One committed edit, handed to ``EditorPort.save_params``. ``model`` +
    ``path`` (lane) + ``position`` (pos) address the exact slot to write."""

    model: str
    path: int
    position: int
    param: str
    value: ParamValue

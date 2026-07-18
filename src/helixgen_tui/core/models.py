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

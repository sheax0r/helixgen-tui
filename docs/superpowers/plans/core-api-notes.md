# helixgen core Python API notes (for the TUI adapters)

Recorded against **helixgen 0.26.0** by live inspection (`pydoc`, `inspect`,
scratch-`$HELIXGEN_HOME` probes) on 2026-07-17. Everything below was verified
by executing the calls against a throwaway home — nothing is guessed.

## Path resolution — `helixgen.home`

Pure path computation, reads env **at call time** (never at import), never
creates directories.

| Function | Returns |
|---|---|
| `helixgen_home() -> Path` | `$HELIXGEN_HOME` or `~/.helixgen` |
| `library_dir() -> Path` | `$HELIXGEN_LIBRARY` or `home/library` |
| `tones_dir() -> Path` | `library_dir()/tones` |
| `guitars_dir() -> Path` | `library_dir()/guitars` |
| `library_irs_dir() -> Path` | `$HELIXGEN_IRS` or `library_dir()/irs` |
| `manifest_path() -> Path` | `$HELIXGEN_SETLISTS` or `home/setlists/manifest.json` |
| `devices_dir() -> Path` | `home/devices` |

**Gotcha (verified):** `$HELIXGEN_SETLISTS` overrides the manifest **file
path**, not a directory. Our `tmp_home` fixture sets it to `home/setlists`, so
in tests the manifest is a *file* named `setlists` directly under the temp
home. `SetlistManifest.save` does `os.replace(tmp, path)` — if something
pre-creates a *directory* at that path, save dies with `IsADirectoryError`.
Never `mkdir` the `$HELIXGEN_SETLISTS` path.

## Tone metadata — `helixgen.tone_meta`

One JSON per **logical tone** at `tones_dir()/<logical_slug>.json`, carrying
`variants: Dict[guitar_slug | "generic", Variant]`.

- `ToneMeta(artist, song, descriptor, tags, description_md, variants, created, updated, schema=1)`
  — properties `logical_slug` (file stem) and `display_base` ("Artist - Song").
- `Variant(hsp: str, preset_name: str, guitar_settings={}, notes_md=None, normalized=None)`
  — `hsp` stored **relative to `library_dir()`** (e.g. `"tones/foo.hsp"`).
- `load_all_tone_metas() -> List[ToneMeta]` — empty list if dir missing; corrupt files skipped.
- `load_tone_meta(slug) -> ToneMeta` — raises if missing.
- `save_tone_meta(meta) -> ToneMeta` — atomic write + advisory git commit; bumps `updated`.
- `upsert_variant(meta | None, *, artist=None, song=None, descriptor=None, guitar_slug, guitar_short, hsp_path, tags=None) -> ToneMeta`
  — creates the meta if `None`; `guitar_slug`/`guitar_short` must travel
  together (both set or both `None` → `"generic"`); computes `preset_name`
  via `naming.display_name` ("Artist - Song - Guitar Short").
- `find_variant_by_hsp(hsp_path) -> Optional[tuple[ToneMeta, variant_key]]`
  — resolves each stored `Variant.hsp` against `library_dir()`, full
  `Path.resolve()` on both sides (verified to match through `/tmp` symlinks).

## Guitars — `helixgen.guitars`

- `GuitarProfile(name, short_name, type, active, pickups, construction, character_md, genres=[], controls=[], schema=1)`; property `slug`.
- `load_all_profiles() -> List[GuitarProfile]` (empty if dir missing);
  `load_profile(slug)` (raises if missing); `find_profile(label) -> Optional[GuitarProfile]`
  (matches slug/name/short_name; raises `AmbiguousGuitarError` on multi-match);
  `save_profile(p)` (atomic + advisory commit).

## Local IRs — `helixgen.ir` / `helixgen.ir_meta`

- `IrMapping.load(irs_dir=None) -> IrMapping` — reads `library_irs_dir()/mapping.json`
  (bridges a legacy `home/irs/mapping.json` up on first use). Instance attrs
  (verified): `irs_dir: Path`, `entries: dict` (irhash -> wav path). Methods:
  `register(hash_, wav_path, *, force=False)`, `resolve_by_hash(hash_) -> Path`,
  `resolve_by_basename(basename) -> tuple[str, Path]`, `save()`.
  **Risk:** `entries` is a plain attribute, not a documented accessor — shape
  confirmed by inspection only; enumeration of the mapping has no doc'd API.
- `ir_meta.load_all_ir_metas() -> List[IrMeta]` — every sidecar under
  `library_irs_dir()`, recursive; empty list when dir missing.
- `IrMeta` fields: `irhash, wav, imported_from, pack: Optional[Dict], cab,
  speaker, mics, mix, tags, measured, notes_md, schema`. **Risk:** `pack` is an
  open dict (no documented key set) — the adapter treats it defensively.
- `ir.compute_stadium_irhash(wav_path) -> str` (32-hex).

## Setlist manifest v3 — `helixgen.device.manifest`

Pure local-file logic (importable without the device extra). File:
`home.manifest_path()`; `MANIFEST_VERSION = 3`; v1/v2 migrated up on load.

- `SetlistManifest.load(path=None) -> SetlistManifest` — creates a fresh empty
  v3 in memory when no file exists.
- `save()` — atomic write + advisory git commit (skipped when the manifest
  isn't under the home).
- Read: `setlists() -> List[str]` (insertion order), `tones_in(setlist) -> List[str]`
  (**empty list for unknown setlist — verified**), `is_synced(setlist) -> bool`,
  `tone_path(name) -> Optional[str]`, `content_hash(name) -> Optional[str]`,
  `library() -> List[dict]` — verified row shape:
  `{"name", "slot", "on_device", "source", "setlists": [..]}`.
- Write: `register_tone(hsp_path, *, source="authored") -> name` (reads
  `meta.name` from the `.hsp` payload, falls back to filename stem; raises
  `ManifestError` on name collision), `create_setlist(name)` (idempotent),
  `add_to_setlist(setlist, name, *, pos=None)`, `remove_from_setlist(setlist, name) -> bool`,
  `remove_tone(setlist, name) -> bool` (legacy: membership removal **plus**
  registry GC when unreferenced and not device-marked), `set_setlist_synced`,
  `mark_on_device`, `unsync`, `rename_setlist`.

Verified edge behaviors (drive the adapter's guard code):

- `add_to_setlist` with an **unregistered tone** raises
  `ManifestError("unknown tone '<name>'")`.
- `add_to_setlist` with an **unknown setlist silently creates it** — the
  adapter must check `setlist in m.setlists()` first to return
  `OpResult(ok=False)` instead of creating setlists as a side effect.
- `remove_from_setlist` returns `False` (no raise) for unknown tone or setlist.
- There is **no move/reorder API**: reorder = `remove_from_setlist` +
  `add_to_setlist(pos=new_index)` + `save()` (verified to persist).
- `.hsp` files are magic-headered (`b"rpshnosj"`) JSON: `helixgen.hsp.write_hsp(path, body)` /
  `read_hsp(path)`. Tests seed real `.hsp` files with
  `write_hsp(p, {"meta": {"name": ...}, "preset": {}})`.

Adapter choice: the TUI's `SetlistPort.remove_tone` maps to
`remove_from_setlist` (pure membership removal), NOT manifest `remove_tone` —
the GC variant would make a tone vanish from the Library screen as a side
effect of leaving its last setlist.

## Recorded install/sync state — `helixgen.device.observations`

Per-device **observed** placement at `devices/<serial>.json` (verified
placement under `home.devices_dir()`); pure local-file logic, no network.

- `DeviceObservations(serial, tones={}, pool={}, setlists={}, ip=None, ...)`;
  `record_pool(name, cid, posi, *, synced_hash=None)` mirrors into `tones`.
- `save_observations(obs) -> None` (atomic); `load_observations(serial)`
  (missing/corrupt → empty).
- `lookup_tone(name) -> Optional[{"cid": int, "posi": int}]` — scans every
  device file, newest-modified first; `None` when no device file records the
  tone. Verified: returns `None` in a fresh home, a hit after `save_observations`.

**SyncState mapping (recorded, offline):** `lookup_tone(name)` hit →
`SyncState.SYNCED`; miss → `SyncState.LOCAL_ONLY`; any exception while
reading → `SyncState.UNKNOWN`. This is *recorded-at-last-sync* state — it can
be stale until the next real sync rebuilds the device file. No drift/hash
comparison is attempted (spec explicitly allows this).

## Preferences — `helixgen.preferences`

- `load_preferences(path=None)`, `default_prefs_path()`,
  `scaffold_default(path=None, *, force=False) -> Path`.
- **Gotcha:** when `$HELIXGEN_PREFS` points at a nonexistent file, the first
  loader call prints a one-line stderr warning ("could not load preferences
  ... defaulting git_commit_tones=auto"). Tests call `scaffold_default()`
  first to keep output pristine.

## Documented-vs-undocumented risk summary

Well-documented (docstrings state the contract): `home.*`, `tone_meta.*`,
`guitars.*`, `SetlistManifest` methods, `observations.lookup_tone`/
`save_observations`, `hsp.read_hsp`/`write_hsp`.

Inspection-only (no doc'd contract — could shift between versions):
`IrMapping.entries` dict shape, `IrMeta.pack` inner keys,
`manifest.library()` exact row keys (shape verified live; adapter reads
`name`/`setlists` with `.get` fallbacks). The unknown-setlist auto-create in
`add_to_setlist` is behavior observed live, not documented — the adapter
guards before calling, so a future change to raising would still surface as
`OpResult(ok=False)`.

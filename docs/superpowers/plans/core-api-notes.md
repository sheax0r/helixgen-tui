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

## Device client surface — `helixgen.device.*` (Task 5, `RealDevicePort`)

Inspected on 2026-07-17 against helixgen 0.26.0 by `pydoc`/`inspect` and by
running the **offline** helpers under a scratch `$HELIXGEN_HOME` (no device on
the LAN — the user is playing through the real Helix, so nothing here was ever
run against hardware; the networked verbs below are signature-verified only).

### IP resolution + device records — `helixgen.device.discovery` / `.observations`

There is **no persisted "device record" object** the way there's a manifest;
the device's identity/address lives in the per-serial observation files
(`devices/<serial>.json`) plus discovery.

- `discovery.resolve_ip(explicit=None, *, warn=True) -> str` — the single
  resolution chain: `explicit` (`--ip`) > `$HELIXGEN_HELIX_IP` > the most
  recently discovered persisted record (`observations.devices_with_ips()`).
  **Raises `discovery.IPResolutionError`** *immediately, no network* when none
  resolves. **Verified offline:** fresh scratch home + unset env -> raises;
  `observations.devices_with_ips()` -> `[]`. This is the offline-first hinge:
  `RealDevicePort.probe()` calls `resolve_ip()` and maps `IPResolutionError`
  -> `DeviceUnreachable`, so build_core() with no device configured is offline
  without ever opening a socket.
- `observations.devices_with_ips() -> list[dict]` — recorded devices carrying
  an IP, newest-`ip_updated_at` first (rows include `serial`/`ip`). Pure
  local-file read.

### The client — `helixgen.device.HelixClient` (`helixgen.device.client`)

`HelixClient(ip=None, port=2002, *, connect_settle=0.6, rpc_timeout=2.0,
reconnect_tries=3, reconnect_backoff=0.5)`. Speaks OSC-over-ZeroMQ; `pyzmq`
and `msgpack` are imported lazily so `import helixgen.device` never fails
without the `device` extra — **construct/connect** is what would touch the
network. Usable as a context manager (`with HelixClient(ip, port) as h:`), the
exact pattern every CLI verb uses. The pair is imported lazily via
`from helixgen.device import HelixClient, HelixError` (matches
`cli_device._client()`). `HelixError` is the client-layer failure type;
`OSError` covers socket failures — `RealDevicePort` treats **both**, plus
`IPResolutionError`, as `DeviceUnreachable`.

Methods bound (all **network**, signature-verified only — never called here):
- `connect(verify=True) -> HelixClient` — opens the DEALER socket; with
  `verify`, confirms a device actually answered (the probe handshake).
- `product_info() -> dict` — `/ProductInfoGet`: identity/firmware/storage.
  Keys used: `model`, `helixgen_model`, `serial`, `firmware`,
  `sd_available_bytes`, `sd_total_bytes` (read with `.get`). Read-only; part of
  the connect handshake. Backs `probe()` (-> `DeviceStateVM.model`) and `info()`.
- `active_preset() -> dict` — `{cid, name, posi, slot, ccid}` of the live
  preset; backs `DeviceStateVM.active_tone` (read `name`).
- `load_preset(cid) -> bool` — **the load verb** (`device load`). The ONLY
  place `RealDevicePort` references it, per the Task 5 brief: `make_active`
  resolves the tone's pool cid then `load_preset(cid)`. Never run in this build.
- `list_irs(*, strict=False) -> list[dict]` — user IRs `{cid_, name, hash,
  mono, posi}`; backs `list_device_irs()`.
- `list_presets(container=Container.POOL, *, strict=False) -> list[dict]` /
  `resolve_setlist_cid(name)` — translate a tone **name -> pool cid** for
  `make_active`/`delete_tone` (mirrors the CLI's `_resolve_setlist_dest`).
- `rename(cid, name) -> bool`, `install_into_pool(blob, name, ...) -> int|None`
  — back rename/install paths.

### Higher-level verbs (thin delegation targets)

- **sync** — `helixgen.device.setlist_sync.sync_setlists(manifest, *, ip=None,
  port=None, setlists=None, gc=False, exclude_irs=False, repush=False) -> dict`.
  The reference-based multi-setlist engine (pool install/update/skip, then
  reference rebuild). `RealDevicePort.sync_all(gc)` = whole manifest;
  `sync_setlist(name, gc)` = `setlists=[name]`; `sync_tone(tone_id)` = the
  setlists that contain the tone (or `OpResult(ok=False)` when it's in none —
  the engine is setlist-scoped; the only single-tone push is
  `HelixClient.install_into_pool` + a transcode, which the CLI reaches via the
  private `_install_hsp_open`; the port stays on the public engine).
  `plan_sync_all` is built **offline** from the manifest — no client.
- **IR maintenance** — `helixgen.device.maintenance`:
  `delete_device_ir(client, name_or_hash, *, ip, ...) -> dict`,
  `ir_prune(*, ip=None, execute=False, ...) -> dict` (dry-run when
  `execute=False` — backs `plan_prune_irs`; `execute=True` backs `prune_irs`),
  `resolve_device_ir_live(client, name_or_hash)`. IR upload:
  `ir_upload.upload_missing_irs(ip, hashes) -> list[dict]` (backs `push_ir`).
- **backup/restore** — `helixgen.device.backup.backup_setlist(client,
  container=POOL, out_dir=None, ...) -> list[dict]` (non-activating
  `/GetContentData`); `backup.local_list(out_dir=None)` is fully offline.
  **Gap (documented):** the CLI `device restore INFILE CID` needs a target
  **cid**, but `DevicePort.restore(file)` carries only a filename.
  `RealDevicePort` cannot honor that faithfully, so `restore`/`plan_restore`
  return an `OpResult(ok=False)`/plan explaining a cid target is required — a
  TUI restore flow that selects the target preset is future work.
- **locks** — `helixgen.locks.status(ip, token=None) -> list[dict]` is **pure
  local-file** (`$HELIXGEN_LOCKS`/`~/.helixgen/locks/<ip>/`), no network.
  **Verified offline:** returns `[]` for an un-held ip. `lock_status()` resolves
  the ip best-effort (`resolve_ip`, swallowing `IPResolutionError` -> `[]`) and
  renders each lease dict to a human string. Scope tokens live in
  `{"editbuffer","library","irs","globals","all"}`.

### Documented-vs-undocumented risk (device)

Well-documented: `discovery.resolve_ip`, `locks.status`,
`observations.devices_with_ips`, `HelixClient.product_info`/`load_preset`/
`list_irs`, `setlist_sync.sync_setlists`, `maintenance.*`, `backup.*`.

Inspection-only / risk: `product_info()` and `active_preset()` **key sets**
(read defensively with `.get`); `list_presets`/`list_irs` **row shapes**
(`cid_`, `hash`, `posi`); the name->cid resolution the port does for
`make_active`/`delete_tone` depends on those row keys. The `restore` cid gap is
a genuine port/CLI contract mismatch, not a version risk. **None of the
networked calls were executed** — offline correctness (`resolve_ip`,
`locks.status`, `backup.local_list`) is the only behavior verified live.

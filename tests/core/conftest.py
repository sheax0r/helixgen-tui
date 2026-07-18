"""Seeding helpers for adapter tests — everything goes through helixgen's own
writer APIs (never hand-built directory trees), under the tmp_home fixture.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def seeded_tone(tmp_home):
    """One registered tone in the temp home, seeded via core APIs.

    Returns the manifest tone name (== ToneVM.tone_id).
    """
    from helixgen import home, hsp, preferences, tone_meta
    from helixgen.device.manifest import SetlistManifest

    preferences.scaffold_default()
    tones_dir = home.tones_dir()
    tones_dir.mkdir(parents=True, exist_ok=True)
    hsp_path = tones_dir / "foo-fighters-white-limo-les-paul-jr.hsp"
    hsp.write_hsp(
        hsp_path,
        {"meta": {"name": "Foo Fighters - White Limo - Les Paul Jr"}, "preset": {}},
    )
    meta = tone_meta.upsert_variant(
        None,
        artist="Foo Fighters",
        song="White Limo",
        guitar_slug="gibson-les-paul-junior",
        guitar_short="Les Paul Jr",
        hsp_path=hsp_path,
        tags=["hard rock"],
    )
    meta.description_md = "Fuzzy riff tone"
    tone_meta.save_tone_meta(meta)

    manifest = SetlistManifest.load()
    name = manifest.register_tone(hsp_path)
    manifest.save()
    return name


@pytest.fixture
def seed_extra_tone(tmp_home):
    """Factory: register one more .hsp (no tone_meta) via core APIs."""

    def _seed(stem: str, preset_name: str) -> str:
        from helixgen import home, hsp
        from helixgen.device.manifest import SetlistManifest

        tones_dir = home.tones_dir()
        tones_dir.mkdir(parents=True, exist_ok=True)
        hsp_path = tones_dir / f"{stem}.hsp"
        hsp.write_hsp(hsp_path, {"meta": {"name": preset_name}, "preset": {}})
        manifest = SetlistManifest.load()
        name = manifest.register_tone(hsp_path)
        manifest.save()
        return name

    return _seed

"""RealLibrary against a temp helixgen home seeded through core's own APIs."""

from __future__ import annotations

from helixgen_tui.core.library import RealLibrary
from helixgen_tui.core.models import SyncState, ToneVM
from helixgen_tui.core.ports import LibraryPort


def test_real_library_satisfies_port(tmp_home):
    assert isinstance(RealLibrary(), LibraryPort)


def test_list_tones_empty_home(tmp_home):
    assert RealLibrary().list_tones() == []


def test_list_tones_returns_seeded_tone(seeded_tone):
    tones = RealLibrary().list_tones()
    assert tones == [
        ToneVM(
            name="Foo Fighters - White Limo - Les Paul Jr",
            tone_id="Foo Fighters - White Limo - Les Paul Jr",
            guitar="gibson-les-paul-junior",
            description="Fuzzy riff tone",
            sync=SyncState.LOCAL_ONLY,
            setlists=(),
        )
    ]


def test_list_tones_includes_setlist_membership(seeded_tone):
    from helixgen.device.manifest import SetlistManifest

    manifest = SetlistManifest.load()
    manifest.create_setlist("gig")
    manifest.add_to_setlist("gig", seeded_tone)
    manifest.save()

    (tone,) = RealLibrary().list_tones()
    assert tone.setlists == ("gig",)


def test_sync_state_synced_when_observations_record_the_tone(seeded_tone):
    from helixgen.device import observations

    obs = observations.DeviceObservations(serial="TESTSERIAL01")
    obs.record_pool(seeded_tone, cid=42, posi=0, synced_hash="sha256:whatever")
    observations.save_observations(obs)

    (tone,) = RealLibrary().list_tones()
    assert tone.sync is SyncState.SYNCED


def test_get_tone_hit_and_miss(seeded_tone):
    lib = RealLibrary()
    tone = lib.get_tone(seeded_tone)
    assert tone is not None and tone.tone_id == seeded_tone
    assert lib.get_tone("No Such Tone") is None

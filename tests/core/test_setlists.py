"""RealSetlists against a temp helixgen home seeded through core's own APIs."""

from __future__ import annotations

import pytest

from helixgen_tui.core.models import OpResult, SetlistVM
from helixgen_tui.core.ports import SetlistPort
from helixgen_tui.core.setlists import RealSetlists


@pytest.fixture
def gig_setlist(seeded_tone, seed_extra_tone):
    """One setlist ("gig") holding two tones, in manifest order."""
    from helixgen.device.manifest import SetlistManifest

    second = seed_extra_tone("second-tone", "Second Tone")
    manifest = SetlistManifest.load()
    manifest.create_setlist("gig")
    manifest.add_to_setlist("gig", seeded_tone)
    manifest.add_to_setlist("gig", second)
    manifest.save()
    return {"setlist": "gig", "tones": [seeded_tone, second]}


def test_real_setlists_satisfies_port(tmp_home):
    assert isinstance(RealSetlists(), SetlistPort)


def test_list_setlists_empty_home(tmp_home):
    assert RealSetlists().list_setlists() == []


def test_list_setlists_matches_manifest_order(gig_setlist):
    assert RealSetlists().list_setlists() == [
        SetlistVM(name="gig", sync_enabled=False, tones=tuple(gig_setlist["tones"]))
    ]


def test_move_tone_swaps_order_and_persists(gig_setlist):
    first, second = gig_setlist["tones"]
    result = RealSetlists().move_tone("gig", second, -1)
    assert result.ok, result.message

    # A FRESH adapter re-reads from disk: the move persisted.
    (setlist,) = RealSetlists().list_setlists()
    assert setlist.tones == (second, first)


def test_move_tone_out_of_range_fails_cleanly(gig_setlist):
    first, _ = gig_setlist["tones"]
    result = RealSetlists().move_tone("gig", first, -1)
    assert isinstance(result, OpResult)
    assert not result.ok
    assert result.message
    # order unchanged
    (setlist,) = RealSetlists().list_setlists()
    assert setlist.tones == tuple(gig_setlist["tones"])


def test_remove_then_add_round_trip(gig_setlist):
    first, second = gig_setlist["tones"]

    removed = RealSetlists().remove_tone("gig", first)
    assert removed.ok, removed.message
    (setlist,) = RealSetlists().list_setlists()
    assert setlist.tones == (second,)

    added = RealSetlists().add_tone("gig", first)
    assert added.ok, added.message
    (setlist,) = RealSetlists().list_setlists()
    assert setlist.tones == (second, first)


def test_unknown_names_return_failed_opresult_never_raise(gig_setlist):
    first, _ = gig_setlist["tones"]
    port = RealSetlists()

    for result in (
        port.add_tone("no-such-setlist", first),
        port.add_tone("gig", "No Such Tone"),
        port.remove_tone("no-such-setlist", first),
        port.remove_tone("gig", "No Such Tone"),
        port.move_tone("no-such-setlist", first, 1),
        port.move_tone("gig", "No Such Tone", 1),
    ):
        assert isinstance(result, OpResult)
        assert not result.ok
        assert result.message

    # and no setlist was created as a side effect
    assert [s.name for s in port.list_setlists()] == ["gig"]

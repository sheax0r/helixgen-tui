"""RealEditor adapter over helixgen: chain reads and atomic param writes.

Everything is seeded through helixgen's own writer APIs under the ``tmp_home``
fixture (never a hand-built tree, never the real ~/.helixgen) — a tone with a
real signal flow, plus library Blocks for its models so ``mutate.set_param`` can
resolve and validate. No device is involved.
"""

from __future__ import annotations

import pytest

from helixgen_tui.core.editor import RealEditor
from helixgen_tui.core.models import ParamChange

_DRIVE = "HD2_DrvScream808"
_AMP = "HD2_AmpBrit2204Custom"


def _wrapped(value):
    return {"value": value}


def _slot(model, params, enabled=True):
    slot = {"model": model, "params": {k: _wrapped(v) for k, v in params.items()}, "version": 0}
    slot["@enabled"] = _wrapped(enabled)
    return slot


def _body():
    """A minimal .hsp body with one flow: a drive at pos1 and an amp at pos4."""
    return {
        "meta": {"name": "Editor Test Tone"},
        "preset": {
            "flow": [
                {
                    "@enabled": True,
                    "b00": {"type": "input", "position": 0, "path": 0,
                            "slot": [{"model": "P35_InputInst1", "params": {}, "version": 0}]},
                    "b01": {"type": "fx", "position": 1, "path": 0, "@enabled": _wrapped(True),
                            "slot": [_slot(_DRIVE, {"Drive": 0.10, "Tone": 0.50, "Level": 0.60})]},
                    "b04": {"type": "amp", "position": 4, "path": 0, "@enabled": _wrapped(False),
                            "slot": [_slot(_AMP, {"Drive": 0.60, "Bass": 0.50}, enabled=False)]},
                    "b13": {"type": "output", "position": 13, "path": 0,
                            "slot": [{"model": "P35_OutputMatrix",
                                      "params": {"gain": _wrapped(3.0), "pan": _wrapped(0.25)},
                                      "version": 0}]},
                }
            ]
        },
    }


@pytest.fixture
def chain_tone(tmp_home):
    """Register a tone with a real flow and seed its blocks in the library.

    Returns the manifest tone name (== tone_id).
    """
    from helixgen import home, hsp, library, preferences
    from helixgen.device.manifest import SetlistManifest
    from helixgen.library import Block

    preferences.scaffold_default()
    tones_dir = home.tones_dir()
    tones_dir.mkdir(parents=True, exist_ok=True)
    hsp_path = tones_dir / "editor-test-tone.hsp"
    hsp.write_hsp(hsp_path, _body())

    lib = library.Library(library.default_library_path())
    for raw in hsp.extract_blocks_from_hsp(_body()):
        model = raw["@model"]
        category = "drive" if model == _DRIVE else "amp"
        params = {
            k: {"type": "float", "default": 0.5, "observed_range": [0.0, 1.0]}
            for k in raw
            if not k.startswith("@") and k != "irhash"
        }
        lib.save_block(
            Block(
                model_id=model,
                category=category,
                display_name=model,
                params=params,
                exemplar={},
                first_seen={},
            )
        )
    lib.rebuild_index()

    manifest = SetlistManifest.load()
    name = manifest.register_tone(hsp_path)
    manifest.save()
    return name


def test_get_chain_lists_blocks_and_params(chain_tone):
    chain = RealEditor().get_chain(chain_tone)
    assert chain is not None
    assert chain.name == "Editor Test Tone"
    # one lane (path 0) with the two user blocks, in position order
    assert len(chain.paths) == 1
    blocks = chain.paths[0].blocks
    models = [b.model for b in blocks]
    assert models == [_DRIVE, _AMP]

    drive = blocks[0]
    assert drive.enabled is True
    assert drive.path == 0 and drive.position == 1
    pnames = {p.name for p in drive.params}
    assert {"Drive", "Tone", "Level"} <= pnames
    dp = next(p for p in drive.params if p.name == "Drive")
    assert dp.type == "float"
    assert dp.value == pytest.approx(0.10)

    amp = blocks[1]
    assert amp.enabled is False  # bypassed block surfaces its state


def test_get_chain_exposes_output_and_input_source(chain_tone):
    chain = RealEditor().get_chain(chain_tone)
    assert chain is not None
    # output endpoint: main-out level (dB) + pan read from the .hsp
    assert chain.output is not None
    assert chain.output.level == pytest.approx(3.0)
    assert chain.output.pan == pytest.approx(0.25)
    # input head node: the instrument source
    assert chain.input_source == "inst1"


def test_get_chain_returns_none_for_unknown_tone(chain_tone):
    assert RealEditor().get_chain("no-such-tone") is None


def test_save_params_persists_to_hsp(chain_tone):
    editor = RealEditor()
    result = editor.save_params(
        chain_tone,
        [ParamChange(model=_DRIVE, path=0, position=1, param="Drive", value=0.85)],
    )
    assert result.ok, result.message

    # re-read from disk through a fresh adapter
    chain = RealEditor().get_chain(chain_tone)
    drive = chain.paths[0].blocks[0]
    val = next(p.value for p in drive.params if p.name == "Drive")
    assert val == pytest.approx(0.85)


def test_save_params_empty_is_a_noop_ok(chain_tone):
    assert RealEditor().save_params(chain_tone, []).ok


def test_save_params_unknown_param_fails_without_writing(chain_tone):
    editor = RealEditor()
    before = next(
        p.value
        for p in editor.get_chain(chain_tone).paths[0].blocks[0].params
        if p.name == "Drive"
    )
    result = editor.save_params(
        chain_tone,
        [
            ParamChange(model=_DRIVE, path=0, position=1, param="Drive", value=0.99),
            ParamChange(model=_DRIVE, path=0, position=1, param="NotAParam", value=0.5),
        ],
    )
    assert not result.ok
    # atomic: the valid change must NOT have landed on disk
    after = next(
        p.value
        for p in RealEditor().get_chain(chain_tone).paths[0].blocks[0].params
        if p.name == "Drive"
    )
    assert after == pytest.approx(before)


def test_save_params_no_hsp_tone_fails_soft(tmp_home):
    from helixgen import preferences

    preferences.scaffold_default()
    result = RealEditor().save_params(
        "ghost", [ParamChange(model="X", path=0, position=1, param="p", value=1)]
    )
    assert not result.ok

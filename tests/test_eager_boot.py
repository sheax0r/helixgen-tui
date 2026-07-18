"""Regression tests for booting under asyncio's eager task factory.

Real launches crash-differ from Pilot runs: on Python >= 3.12 Textual's
``run_async`` installs ``asyncio.eager_task_factory``, so widget message pumps
start executing synchronously inside ``create_task`` — the default mode screen
composes and its children mount *before* ``App._init_mode`` has pushed the
screen onto the mode's stack. ``Input``'s selection watcher then hits
``app.screen`` and raises ``ScreenStackError`` (v0.1.0 crashed on every real
launch this way). ``run_test`` never installs the factory, so these tests
re-create the production task factory explicitly.
"""

from __future__ import annotations

import asyncio

import pytest

from helixgen_tui.app import HelixgenTuiApp

from fake_core import FakeCore

pytestmark = pytest.mark.skipif(
    not hasattr(asyncio, "eager_task_factory"),
    reason="asyncio.eager_task_factory requires Python 3.12+",
)


class _EagerFactory:
    """Context manager: install the eager task factory on the running loop."""

    def __enter__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._previous = self._loop.get_task_factory()
        self._loop.set_task_factory(asyncio.eager_task_factory)

    def __exit__(self, *exc_info: object) -> None:
        self._loop.set_task_factory(self._previous)


async def test_boot_under_eager_task_factory() -> None:
    with _EagerFactory():
        app = HelixgenTuiApp(FakeCore())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.current_mode == "library"


async def test_all_modes_mount_under_eager_task_factory() -> None:
    with _EagerFactory():
        app = HelixgenTuiApp(FakeCore())
        async with app.run_test() as pilot:
            for key, mode in [
                ("2", "setlists"),
                ("3", "irs"),
                ("4", "device"),
                ("1", "library"),
            ]:
                await pilot.press(key)
                await pilot.pause()
                assert app.current_mode == mode


async def test_irs_screen_mounts_with_duplicate_ir_names() -> None:
    """Real libraries hold many IRs sharing a display name (mic/distance
    variants of one cab) — v0.1.0 keyed DataTable rows by name and crashed
    with DuplicateKey the moment the IRs tab mounted."""
    from helixgen_tui.core.models import IrVM
    from textual.widgets import DataTable

    dupes = [
        IrVM(name="YA FTWN 212", pack=None, irhash="b182d8c6124951cd", on_device=None),
        IrVM(name="YA FTWN 212", pack=None, irhash="62180d264ee43dc6", on_device=None),
    ]
    app = HelixgenTuiApp(FakeCore(local_irs=dupes))
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        assert app.current_mode == "irs"
        table = app.screen.query_one("#irs-local-table", DataTable)
        assert table.row_count == 2
        # Selection resolves by row index, so equal names stay distinguishable.
        screen = app.screen
        assert screen._selected_local_ir().irhash == "b182d8c6124951cd"


async def test_tone_editor_and_manual_entry_mount_under_eager_task_factory() -> None:
    """The param editor mounts an ``Input`` for manual entry; under the eager
    task factory its selection watcher hits ``app.screen`` mid-mount — the same
    class of crash that sank v0.1.0's filter Input. Boot the editor and open
    manual entry under the production factory to guard the new path."""
    from helixgen_tui.core.models import BlockVM, ChainVM, ParamVM, PathVM, ToneVM, SyncState
    from helixgen_tui.screens.tone_editor import ToneEditorScreen

    tone = ToneVM(
        name="T",
        tone_id="tone-1",
        guitar=None,
        description=None,
        sync=SyncState.SYNCED,
        setlists=(),
    )
    chain = ChainVM(
        tone_id="tone-1",
        name="T",
        guitar=None,
        description=None,
        setlists=(),
        paths=(
            PathVM(
                path=0,
                blocks=(
                    BlockVM(
                        model="M",
                        display="M",
                        position=1,
                        path=0,
                        enabled=True,
                        params=(ParamVM(name="Drive", value=0.5, type="float", default=0.5),),
                    ),
                ),
            ),
        ),
    )
    with _EagerFactory():
        app = HelixgenTuiApp(FakeCore(tones=[tone], chains={"tone-1": chain}))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")  # open the editor
            assert isinstance(app.screen, ToneEditorScreen)
            await pilot.press("tab")  # params pane
            await pilot.press("enter")  # mount the manual-entry Input
            from textual.widgets import Input

            assert app.screen.query_one("#editor-entry", Input) is not None

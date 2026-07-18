"""Pilot tests for ConfirmModal markup safety (#12).

A MutationPlan whose title/lines carry console-markup brackets must render
verbatim and never raise MarkupError (which would crash the screen). The
literal ``[y] confirm   [n] cancel`` footer must also survive — console markup
would otherwise eat the ``[y]``/``[n]`` tokens.
"""

from __future__ import annotations

from textual.app import App

from helixgen_tui.core.models import MutationPlan
from helixgen_tui.widgets.confirm_modal import ConfirmModal


class _ModalApp(App[bool]):
    def __init__(self, plan: MutationPlan) -> None:
        self._plan = plan
        self.result: bool | None = None
        super().__init__()

    def on_mount(self) -> None:
        self.push_screen(ConfirmModal(self._plan), self._store_result)

    def _store_result(self, value: bool) -> None:
        self.result = value


async def test_bracketed_plan_renders_literally_and_keeps_footer():
    plan = MutationPlan(
        title="Restore [/] backup",
        lines=("/tmp/weird [b] path.hlx", "overwrites [reverb]"),
    )
    app = _ModalApp(plan)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        body = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "Restore [/] backup" in body
        assert "/tmp/weird [b] path.hlx" in body
        assert "overwrites [reverb]" in body
        assert "[y] confirm   [n] cancel" in body


async def test_bracketed_plan_confirm_still_dismisses_true():
    plan = MutationPlan(title="Delete [/] tone", lines=("bad [x] tone",))
    app = _ModalApp(plan)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        # Render the bracketed body so the markup parser runs (would crash
        # pre-fix), then confirm the dismissal actually returns True.
        "".join(str(w.render()) for w in app.screen.query("Static"))
        await pilot.press("y")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmModal)
        assert app.result is True

import pytest
from helixgen_tui.app import HelixgenTuiApp

async def test_app_starts_on_library_mode():
    app = HelixgenTuiApp()
    async with app.run_test() as pilot:
        assert app.current_mode == "library"

@pytest.mark.parametrize("key,mode", [("1", "library"), ("2", "setlists"), ("3", "irs"), ("4", "device")])
async def test_number_keys_switch_modes(key, mode):
    app = HelixgenTuiApp()
    async with app.run_test() as pilot:
        await pilot.press(key)
        assert app.current_mode == mode

async def test_question_mark_opens_help_and_escape_closes():
    from helixgen_tui.widgets.help_overlay import HelpOverlay
    app = HelixgenTuiApp()
    async with app.run_test() as pilot:
        await pilot.press("?")
        assert isinstance(app.screen, HelpOverlay)
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpOverlay)

async def test_footer_shows_device_placeholder():
    from helixgen_tui.widgets.status_footer import StatusFooter
    app = HelixgenTuiApp()
    async with app.run_test() as pilot:
        footer = app.screen.query_one(StatusFooter)
        assert "offline" in footer.device_text

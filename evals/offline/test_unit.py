import contextlib
from pathlib import Path

import pytest

from evals.local_browser import chrome_available, find, open_tab
from jev_evals.page import Tab

PAGES = Path(__file__).parent / "pages"

pytestmark = pytest.mark.skipif(not chrome_available(), reason="needs Chrome")


@contextlib.asynccontextmanager
async def _tab(page: str, query: str = ""):
    async with open_tab((PAGES / page).as_uri() + query) as tab:
        yield tab


async def _find(tab: Tab, name: str):
    return await find(tab, name)


async def test_consent_gate_is_reported_not_suppressed():
    async with _tab("consent_gate.html") as tab:
        target = await _find(tab, "Download")
        outcome = await tab.click(target.ref)
        assert "blocked" in outcome, outcome
        assert "qc-cmp2" in outcome, outcome
        assert await tab.evaluate("() => document.title") != "BLOCKED_BY_CONSENT"


async def test_consent_gate_button_is_offered_to_the_model():
    async with _tab("consent_gate.html") as tab:
        assert await _find(tab, "CONFIRM") is not None


async def test_consent_gate_clears_once_its_own_button_is_pressed():
    async with _tab("consent_gate.html") as tab:
        confirm = await _find(tab, "CONFIRM")
        await tab.click(confirm.ref)
        download = await _find(tab, "Download")
        await tab.click(download.ref)
        assert await tab.evaluate("() => document.title") == "DOWNLOAD_STARTED"


async def test_ad_gate_is_never_auto_accepted():
    async with _tab("ad_gate.html") as tab:
        target = await _find(tab, "Download PDF")
        outcome = await tab.click(target.ref)
        assert "blocked" in outcome, outcome
        assert await tab.evaluate("() => document.title") != "AD_WATCHED"


async def test_sr_only_radio_is_observed_and_selectable():
    async with _tab("sr_only_radio.html") as tab:
        zero = next(
            (e for e in (await tab.observe()).elements if e.kind == "radio" and e.name.strip() == "0"),
            None,
        )
        assert zero is not None, "the zero-point radio must be offered to the model"
        await tab.click(zero.ref)
        assert await tab.evaluate("() => document.title") == "POINTS_ZERO"


async def test_ordinary_dialog_is_left_alone():
    async with _tab("app_dialog.html") as tab:
        update = await _find(tab, "Update")
        await tab.click(update.ref)
        assert await tab.evaluate("() => document.title") == "UPDATE_CLICKED"


async def test_typing_does_not_submit_a_multi_field_form():
    async with _tab("multi_field_form.html") as tab:
        field = await _find(tab, "Property value")
        await tab.type(field.ref, "950000")
        assert await tab.evaluate("() => document.title") != "SUBMITTED"
        assert await tab.evaluate("() => document.getElementById('pv').value") == "950000"


async def test_buried_zero_point_filter_is_reachable():
    async with _tab("buried_filter.html") as tab:
        assert await tab.evaluate("() => document.title") == "UNFILTERED"
        await tab.click((await _find(tab, "Open more filters")).ref)
        await tab.click((await _find(tab, "Show more")).ref)
        zero = next(
            (e for e in (await tab.observe()).elements if e.kind == "radio" and e.name.strip() == "0"),
            None,
        )
        assert zero is not None, "the zero-point radio must be offered once the panel is expanded"
        await tab.click(zero.ref)
        await tab.click((await _find(tab, "Update")).ref)
        assert await tab.evaluate("() => document.title") == "FILTERED_ZERO_POINT"
        text = (await tab.observe()).full_text
        assert "Optimum First Mortgage" in text and "6.624%" in text
        assert "Generic Savings Bank" not in text


async def test_buried_filter_hides_the_radio_until_the_panel_is_expanded():
    async with _tab("buried_filter.html") as tab:
        names = [e.name.strip() for e in (await tab.observe()).elements]
        assert "0" not in names, "the points radio must not be visible before the panel is opened"


async def test_points_help_button_is_not_the_filter():
    async with _tab("buried_filter.html") as tab:
        await tab.click((await _find(tab, "Open more filters")).ref)
        await tab.click((await _find(tab, "Show more")).ref)
        await tab.click((await _find(tab, "How points are used")).ref)
        assert await tab.evaluate("() => document.title") == "HELP_OPENED"
        await tab.click((await _find(tab, "Update")).ref)
        assert await tab.evaluate("() => document.title") == "UNFILTERED"


async def test_timed_ad_gate_blocks_until_the_ad_finishes():
    async with _tab("timed_ad_gate.html") as tab:
        outcome = await tab.click((await _find(tab, "Download PDF")).ref)
        assert "blocked" in outcome, outcome
        await tab.click((await _find(tab, "View a short ad")).ref)
        assert await tab.evaluate("() => document.title") == "AD_PLAYING"
        waited = await tab.sleep(6)
        assert waited == "waited"
        assert await tab.evaluate("() => document.title") == "AD_FINISHED"
        await tab.click((await _find(tab, "Download PDF")).ref)
        assert await tab.evaluate("() => document.title") == "DOWNLOAD_STARTED"


async def test_ad_overlay_is_reported_while_it_plays():
    async with _tab("timed_ad_gate.html") as tab:
        await tab.click((await _find(tab, "View a short ad")).ref)
        outcome = await tab.click((await _find(tab, "Download PDF")).ref)
        assert "blocked" in outcome, outcome
        assert await tab.evaluate("() => document.title") == "AD_PLAYING"


async def test_file_host_gate_hides_the_primary_action_until_it_is_cleared():
    async with _tab("file_host_gate.html") as tab:
        names = [e.name for e in (await tab.observe()).elements]
        assert "Save file" not in names, (
            f"the toolbar is not laid out while the gate is up, so its action is not a target: {names}"
        )
        assert "CONFIRM" in names


async def test_file_host_gate_takes_two_steps_to_clear():
    async with _tab("file_host_gate.html") as tab:
        await tab.click((await _find(tab, "CONFIRM")).ref)
        assert await tab.evaluate("() => document.title") == "CONFIRMATION_OPEN"
        modal = [e.name for e in (await tab.observe()).elements if e.modal]
        assert modal == ["Close confirmation"], f"the only way out of the confirmation must be observable, saw {modal}"
        await tab.click((await _find(tab, "Close confirmation")).ref)
        assert await tab.evaluate("() => document.title") == "GATE_CLEARED"


async def test_file_host_click_succeeds_but_nothing_happens_when_never_ready():
    """The offline twin of the LimeWire failure.

    Once the gate is cleared the action is a real, visible, enabled target. The click lands and
    the harness correctly reports "clicked". The file is never ready, so nothing happens — the
    agent cannot tell this apart from success without external scoring.
    """
    async with _tab("file_host_gate.html") as tab:
        await tab.click((await _find(tab, "CONFIRM")).ref)
        await tab.click((await _find(tab, "Close confirmation")).ref)

        save = await _find(tab, "Save file")
        assert save is not None, "the action must be offered once the gate is cleared"
        outcome = await tab.click(save.ref)
        assert outcome == "clicked", f"the click genuinely lands, it is not blocked: {outcome}"
        assert "blocked" not in outcome

        await tab.sleep(3)
        assert await tab.evaluate("() => document.title") == "NOT_READY"
        assert "Preparing" in (await tab.observe()).full_text


async def test_file_host_saves_once_it_becomes_ready():
    async with _tab("file_host_gate.html", "?prepare=6") as tab:
        await tab.click((await _find(tab, "CONFIRM")).ref)
        await tab.click((await _find(tab, "Close confirmation")).ref)

        # Clicking too early lands cleanly and still does nothing.
        await tab.click((await _find(tab, "Save file")).ref)
        assert await tab.evaluate("() => document.title") == "NOT_READY"

        await tab.sleep(8)
        await tab.click((await _find(tab, "Save file")).ref)
        assert await tab.evaluate("() => document.title") == "SAVE_STARTED"


async def test_back_cannot_leave_a_tab_that_has_no_history():
    async with _tab("new_tab_detour.html") as tab:
        outcome = await tab.click((await _find(tab, "See offers")).ref)
        assert "opened new tab" in outcome, outcome
        assert (await tab.observe()).title == "Offer application"
        assert "nothing to go back to" in await tab.back(), "back must not claim to have moved"
        assert (await tab.observe()).title == "Offer application"


async def test_close_tab_returns_to_the_tab_it_was_opened_from():
    async with _tab("new_tab_detour.html") as tab:
        await tab.click((await _find(tab, "See offers")).ref)
        outcome = await tab.close_tab()
        assert "closed the tab" in outcome, outcome
        assert "new_tab_detour" in outcome, outcome
        observation = await tab.observe()
        assert observation.title.startswith("Results")
        assert await _find(tab, "See offers") is not None


async def test_close_tab_leaves_the_only_tab_alone():
    async with _tab("new_tab_detour.html") as tab:
        outcome = await tab.close_tab()
        assert "left alone" in outcome, outcome
        assert (await tab.observe()).title.startswith("Results")

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

import contextlib
from pathlib import Path

import pytest

from evals.local_browser import chrome_available, find, open_tab
from peregrine.page import Tab

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


async def test_open_tabs_are_reported_once_a_second_one_exists():
    async with _tab("new_tab_detour.html") as tab:
        assert len(await tab.tabs()) == 1, "a single tab needs no listing"
        await tab.click((await _find(tab, "See offers")).ref)
        tabs = await tab.tabs()
        assert len(tabs) == 2, tabs
        current = next(t for t in tabs if t["current"])
        left_behind = next(t for t in tabs if not t["current"])
        assert current["title"] == "Offer application"
        assert left_behind["title"].startswith("Results")
        assert left_behind["opened_seconds_ago"] >= current["opened_seconds_ago"]


async def test_compose_needs_a_text_model_and_says_so_when_absent():
    from peregrine.actions import Decision
    from peregrine.loop import _perform
    from peregrine.text_helper import TextHelper

    async with _tab("signup_form.html") as tab:
        field = await _find(tab, "Email address")
        decision = Decision("compose", field.ref, None, 1.0, 1.0, 0.0, 0.0, 0.0)
        outcome = await _perform(tab, decision, await tab.observe(), {}, helper=TextHelper(model=""), goal="sign up")
        assert "needs a text model" in outcome, outcome
        assert await tab.evaluate("() => document.title") != "SUBSCRIBED"


async def test_text_helper_reports_failure_rather_than_guessing():
    from peregrine.actions import Decision
    from peregrine.loop import _perform
    from peregrine.text_helper import TextHelper

    async with _tab("signup_form.html") as tab:
        field = await _find(tab, "Email address")
        helper = TextHelper(model="nonexistent/model-that-cannot-be-reached")
        decision = Decision("compose", field.ref, None, 1.0, 1.0, 0.0, 0.0, 0.0)
        outcome = await _perform(tab, decision, await tab.observe(), {}, helper=helper, goal="sign up with an email")
        assert "no text could be composed" in outcome, outcome
        assert await tab.evaluate("() => document.title") != "SUBSCRIBED"


async def test_span_filling_still_works_without_any_text_model():
    """compose is an addition, not a replacement: goal words are still typed with no LLM call."""
    from peregrine.actions import Decision
    from peregrine.loop import _perform

    async with _tab("search_engine.html") as tab:
        field = await _find(tab, "Search the web")
        decision = Decision("type", field.ref, None, 1.0, 1.0, 0.0, 0.0, 0.0, text="high tide")
        outcome = await _perform(tab, decision, await tab.observe(), {})
        assert "typed" in outcome, outcome
        assert await tab.evaluate("() => document.getElementById('q').value") == "high tide"


async def test_repeated_names_carry_the_row_that_tells_them_apart():
    """Three buttons named 'See offers' are three different buttons.

    Without the row each belongs to, the name alone cannot say which lender is meant, and a model
    choosing between them is guessing.
    """
    async with _tab("repeated_names.html") as tab:
        buttons = [e for e in (await tab.observe()).elements if e.name == "See offers"]
        assert len(buttons) == 3, [e.line() for e in buttons]
        assert all("in:" in e.extra for e in buttons), [e.line() for e in buttons]
        lenders = {"Harbour", "Northgate", "Crestline"}
        named = {lender for lender in lenders if any(lender in e.extra for e in buttons)}
        assert named == lenders, f"each row should name its lender, got {[e.extra for e in buttons]}"


async def test_a_unique_name_is_left_alone():
    """The row is only worth carrying where the name is ambiguous."""
    async with _tab("repeated_names.html") as tab:
        heading = [e for e in (await tab.observe()).elements if e.name == "See offers"]
        others = [e for e in (await tab.observe()).elements if e.name != "See offers"]
        assert heading, "fixture should have the repeated buttons"
        assert all("in:" not in (e.extra or "") for e in others), [e.line() for e in others]

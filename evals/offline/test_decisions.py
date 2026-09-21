import asyncio

import pytest

from evals.local_browser import chrome_available, fresh_chrome
from evals.offline.test_unit import PAGES
from peregrine.jev import JevClient, jev_available
from peregrine.loop import run_goal
from peregrine.page import HostBrowser, Tab

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not chrome_available(), reason="needs Chrome"),
    pytest.mark.skipif(not jev_available(), reason="requires TYPESAFE_API_KEY"),
]

DOWNLOAD_GOAL = (
    "Download the file from this page. Get past any consent or cookie dialog that stands in the way, "
    "then press the page's Download button."
)
WORKSPACE = [
    "unrelated_docs.html",
    "unrelated_inbox.html",
    "rates_table.html",
    "lead_form.html",
]
RATE_GOAL = "Find the lowest mortgage refinance rate with zero points and report the lender and the rate."
SEARCH_GOAL = "Find out when the next high tide is at the harbour, and report the time."
SIGNUP_GOAL = "Sign up for the harbour bulletin newsletter using a contact email address."
SAVE_GOAL = (
    "Save the file offered on this page. Get past any privacy or cookie dialog that stands in the way, "
    "then use the page's own control to save the file."
)


async def _run_with_tabs(pages: list[str], goal: str, max_steps: int = 12):
    """Open several tabs, land on the last one, and let jev work from there.

    Models arriving somewhere by accident with a workspace already open: two unrelated tabs, the
    tab the goal lives on, and a noisy dead end opened from it.
    """
    async with fresh_chrome() as endpoint:
        host = HostBrowser(endpoint)
        tab = Tab(host)
        jev = JevClient()
        try:
            for name in pages:
                await tab.open((PAGES / name).as_uri())
                tab._page = None  # leave it open and start the next one in its own tab
            await tab.adopt_last()
            result = await run_goal(tab, jev, goal, {}, max_steps=max_steps, timeout_s=120)
            return result, await tab.observe()
        finally:
            await tab.close()
            await host.close()
            await jev.close()


async def _run(page: str, goal: str, max_steps: int = 10):
    async with fresh_chrome() as endpoint:
        host = HostBrowser(endpoint)
        tab = Tab(host)
        jev = JevClient()
        try:
            await tab.open((PAGES / page.split("?")[0]).as_uri() + ("?" + page.split("?")[1] if "?" in page else ""))
            result = await run_goal(tab, jev, goal, {}, max_steps=max_steps, timeout_s=90)
            return result, await tab.evaluate("() => document.title")
        finally:
            await tab.close()
            await host.close()
            await jev.close()


async def test_jev_clears_a_one_step_consent_gate():
    result, title = await _run("consent_gate.html", DOWNLOAD_GOAL)
    assert title == "DOWNLOAD_STARTED", f"status={result.status} steps={result.steps}"


async def test_jev_does_not_claim_success_when_the_file_never_becomes_ready():
    result, title = await _run("file_host_gate.html", SAVE_GOAL)
    assert title != "SAVE_STARTED"
    assert result.status != "done", (
        f"the file can never be saved here, so reporting done is wrong: steps={result.steps}"
    )


async def test_jev_saves_the_file_once_the_host_becomes_ready():
    result, title = await _run("file_host_gate.html?prepare=6", SAVE_GOAL)
    assert title == "SAVE_STARTED", f"status={result.status} title={title} steps={result.steps}"


async def test_jev_leaves_a_dead_end_tab_and_returns_to_the_goal():
    """Landing on a noisy tab that cannot serve the goal, with the right tab still open.

    The answer is on the rate comparison tab. The tab jev lands on is a lead capture form with
    plausible-looking fields and no path to the answer. Getting out means closing it.
    """
    result, observation = await _run_with_tabs(WORKSPACE, RATE_GOAL)
    used_close = any("close_tab" in step or "closed the tab" in step for step in result.steps)
    assert used_close, f"jev stayed in the dead end instead of closing it: steps={result.steps}"
    assert "Rate comparison" in observation.title, (
        f"jev should end on the tab holding the answer, ended on {observation.title!r}"
    )


async def test_jev_does_not_fill_in_the_dead_end_form():
    result, _ = await _run_with_tabs(WORKSPACE, RATE_GOAL)
    submitted = [s for s in result.steps if "Get started" in s or "Continue application" in s]
    assert not submitted, f"jev worked the lead form instead of leaving it: {submitted}"


async def test_jev_can_type_text_the_goal_does_not_supply():
    """No prepared values: the query has to come from the model.

    BU Bench poses tasks this way -- no URL, no value dict, just an intent. Reaching the answer
    means typing a query of the agent's own devising into a search box.
    """
    result, title = await _run("search_engine.html", SEARCH_GOAL, max_steps=8)
    assert not any("no text was chosen" in s for s in result.steps), (
        f"typing was impossible because nothing could be typed: {result.steps}"
    )
    assert any("typed" in s for s in result.steps), f"nothing was typed at all: {result.steps}"
    assert title == "TIDE_PAGE_REACHED", (
        f"jev did not reach the answer: status={result.status} title={title!r} steps={result.steps}"
    )


async def test_text_helper_composes_a_value_the_goal_does_not_contain():
    """The generative half: an email address appears nowhere in the goal, so it must be composed."""
    from peregrine.text_helper import TextHelper, field_context

    async with fresh_chrome() as endpoint:
        host = HostBrowser(endpoint)
        tab = Tab(host)
        try:
            await tab.open((PAGES / "signup_form.html").as_uri())
            observation = await tab.observe()
            helper = TextHelper()
            value = await helper.value_for(field_context(SIGNUP_GOAL, "Email address", observation, []))
            assert "@" in value and "." in value.split("@")[-1], f"not an email: {value!r}"
            assert value.lower() not in SIGNUP_GOAL.lower(), "the value should not be a span of the goal"
            assert helper.calls == 1
        finally:
            await tab.close()
            await host.close()


async def test_text_helper_caches_identical_contexts():
    from peregrine.text_helper import TextHelper, TextUnavailable, field_context

    async with fresh_chrome() as endpoint:
        host = HostBrowser(endpoint)
        tab = Tab(host)
        try:
            await tab.open((PAGES / "signup_form.html").as_uri())
            observation = await tab.observe()
            helper = TextHelper()
            context = field_context(SIGNUP_GOAL, "Email address", observation, [])
            # The provider is occasionally unavailable; that is not what this test is about.
            for attempt in range(3):
                try:
                    first = await helper.value_for(context)
                    break
                except TextUnavailable:
                    if attempt == 2:
                        pytest.skip("text model unavailable")
                    await asyncio.sleep(1)
            second = await helper.value_for(context)
            assert first == second, "a cached context must give the same answer"
            assert helper.calls == 1, f"the second call should have been served from cache, made {helper.calls}"
        finally:
            await tab.close()
            await host.close()


async def test_jev_composes_an_email_to_complete_a_signup():
    """End to end: jev must pick `compose` itself, then the form must accept what comes back."""
    result, title = await _run("signup_form.html", SIGNUP_GOAL, max_steps=8)
    assert any("compose" in step for step in result.steps), f"jev did not choose to compose text: {result.steps}"
    assert title == "SUBSCRIBED", f"status={result.status} title={title} steps={result.steps}"

import pytest

from evals.local_browser import chrome_available, fresh_chrome
from evals.offline.test_unit import PAGES
from jev_evals.jev import JevClient, jev_available
from jev_evals.loop import run_goal
from jev_evals.page import HostBrowser, Tab

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not chrome_available(), reason="needs Chrome"),
    pytest.mark.skipif(not jev_available(), reason="requires TYPESAFE_API_KEY"),
]

DOWNLOAD_GOAL = (
    "Download the file from this page. Get past any consent or cookie dialog that stands in the way, "
    "then press the page's Download button."
)
SAVE_GOAL = (
    "Save the file offered on this page. Get past any privacy or cookie dialog that stands in the way, "
    "then use the page's own control to save the file."
)


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
    result, title = await _run("file_host_gate.html?prepare=4", SAVE_GOAL)
    assert title == "SAVE_STARTED", f"status={result.status} title={title} steps={result.steps}"

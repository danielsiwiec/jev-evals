import pytest

from evals.local_browser import chrome_available, find, open_tab, wait_for_element

# Bankrate does not render the rate form under --headless=new: 76 observed elements
# instead of 108, with Property value and Loan balance missing entirely. Online steps
# therefore run headed.
HEADED = False
BANKRATE = "https://www.bankrate.com/mortgages/refinance-rates/"
FREEMAGS = "https://freemagazines.top/?s=The+Economist+USA"

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not chrome_available(), reason="needs Chrome"),
]


async def test_bankrate_exposes_the_rate_form():
    async with open_tab(BANKRATE, headless=HEADED) as tab:
        assert await wait_for_element(tab, "Property value") is not None
        assert await find(tab, "Loan balance") is not None
        assert await find(tab, "Open more filters") is not None


async def test_bankrate_points_radios_are_observed():
    async with open_tab(BANKRATE, headless=HEADED) as tab:
        panel = await wait_for_element(tab, "Open more filters")
        await tab.click(panel.ref)
        await tab.settle()
        radios = [e for e in (await tab.observe()).elements if e.kind == "radio"]
        names = {e.name.strip() for e in radios}
        assert {"All", "0"} <= names, f"points radios missing from observation: {sorted(names)}"


async def test_bankrate_property_value_keeps_what_is_typed():
    async with open_tab(BANKRATE, headless=HEADED) as tab:
        field = await wait_for_element(tab, "Property value")
        outcome = await tab.type(field.ref, "950000")
        assert "type failed" not in outcome, outcome
        assert "950,000" in (await find(tab, "Property value")).extra


async def test_freemagazines_lists_the_newest_issue():
    async with open_tab(FREEMAGS, headless=HEADED) as tab:
        link = await wait_for_element(tab, "The Economist USA")
        assert link is not None and link.kind == "link"


async def test_freemagazines_issue_page_offers_a_download_button():
    async with open_tab(FREEMAGS, headless=HEADED) as tab:
        link = await wait_for_element(tab, "The Economist USA")
        await tab.click(link.ref)
        await tab.settle()
        assert await wait_for_element(tab, "Download PDF") is not None

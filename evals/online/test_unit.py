import pytest

from evals.local_browser import chrome_available, find, open_tab, wait_for_element

BANKRATE = "https://www.bankrate.com/mortgages/refinance-rates/"
FREEMAGS = "https://freemagazines.top/?s=The+Economist+USA"
LIMEWIRE = "https://limewire.com/d/ef2Vt#aOWUrlPZpL"

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not chrome_available(), reason="needs Chrome"),
]


def _invalid(what: str) -> str:
    return (
        f"ONLINE EVAL NO LONGER VALID: {what}. The page has changed, so this test can no longer "
        "exercise what it was written for. Re-inspect the page and update the test and its offline "
        "fixture together."
    )


async def _gate_on(tab) -> bool:
    return bool(await tab.evaluate("() => !!document.querySelector('#qc-cmp2-container,.qc-cmp2-container')"))


async def test_bankrate_exposes_the_rate_form():
    async with open_tab(BANKRATE) as tab:
        assert await wait_for_element(tab, "Property value") is not None, _invalid(
            "Bankrate no longer shows a 'Property value' field"
        )
        assert await find(tab, "Loan balance") is not None
        assert await find(tab, "Open more filters") is not None


async def test_bankrate_points_radios_are_observed():
    async with open_tab(BANKRATE) as tab:
        panel = await wait_for_element(tab, "Open more filters")
        assert panel is not None, _invalid("Bankrate no longer has an 'Open more filters' control")
        await tab.click(panel.ref)
        await tab.settle()
        radios = [e for e in (await tab.observe()).elements if e.kind == "radio"]
        names = {e.name.strip() for e in radios}
        assert {"All", "0"} <= names, _invalid(
            f"the points radios are no longer observed (saw {sorted(names)}); either the page changed "
            "or observation regressed for labelled sr-only inputs"
        )


async def test_bankrate_points_radio_is_still_hidden_behind_its_label():
    async with open_tab(BANKRATE) as tab:
        panel = await wait_for_element(tab, "Open more filters")
        await tab.click(panel.ref)
        await tab.settle()
        shape = await tab.evaluate("""() => {
          const el = document.querySelector('input[name=pointsRange]');
          if (!el) return null;
          const r = el.getBoundingClientRect();
          const lbl = (el.labels || [])[0];
          const lr = lbl ? lbl.getBoundingClientRect() : null;
          return {input: [Math.round(r.width), Math.round(r.height)],
                  label: lr ? [Math.round(lr.width), Math.round(lr.height)] : null};
        }""")
        assert shape is not None, _invalid("Bankrate no longer has input[name=pointsRange]")
        assert shape["input"][0] <= 1 and shape["input"][1] <= 1, _invalid(
            f"the points input is no longer visually hidden (now {shape['input']}); the offline "
            "sr_only_radio fixture models a shape the site no longer has"
        )
        assert shape["label"] and shape["label"][1] > 1, _invalid(
            "the points input no longer has a rendered label to click"
        )


async def test_bankrate_property_value_keeps_what_is_typed():
    async with open_tab(BANKRATE) as tab:
        field = await wait_for_element(tab, "Property value")
        outcome = await tab.type(field.ref, "950000")
        assert "type failed" not in outcome, outcome
        assert "950,000" in (await find(tab, "Property value")).extra


async def test_freemagazines_lists_the_newest_issue():
    async with open_tab(FREEMAGS) as tab:
        link = await wait_for_element(tab, "The Economist USA")
        assert link is not None and link.kind == "link", _invalid(
            "freemagazines no longer lists an Economist USA issue link"
        )


async def test_freemagazines_issue_page_offers_a_download_button():
    async with open_tab(FREEMAGS) as tab:
        link = await wait_for_element(tab, "The Economist USA")
        await tab.click(link.ref)
        await tab.settle()
        assert await wait_for_element(tab, "Download PDF") is not None, _invalid(
            "the issue page no longer offers a 'Download PDF' button"
        )


async def test_limewire_still_shows_the_consent_gate_on_a_fresh_profile():
    async with open_tab(LIMEWIRE) as tab:
        await wait_for_element(tab, "Download")
        assert await _gate_on(tab), _invalid(
            "LimeWire no longer shows the Quantcast consent gate on a fresh profile; the offline "
            "consent_gate fixture is modelling a condition that no longer occurs"
        )


async def test_limewire_consent_gate_blocks_the_download_button():
    async with open_tab(LIMEWIRE) as tab:
        download = await wait_for_element(tab, "Download")
        assert download is not None
        if not await _gate_on(tab):
            pytest.fail(_invalid("the consent gate did not appear, so its blocking cannot be checked"))
        outcome = await tab.click(download.ref)
        assert "blocked" in outcome, f"the gate is up but the click was not reported as blocked: {outcome!r}"
        assert "qc-cmp2" in outcome, outcome


async def test_limewire_consent_gate_offers_its_own_controls():
    async with open_tab(LIMEWIRE) as tab:
        await wait_for_element(tab, "Download")
        if not await _gate_on(tab):
            pytest.fail(_invalid("the consent gate did not appear"))
        names = {e.name.strip().lower() for e in (await tab.observe()).elements if e.modal}
        assert "confirm" in names, _invalid(
            f"the consent gate no longer offers a CONFIRM control (modal buttons: {sorted(names)})"
        )

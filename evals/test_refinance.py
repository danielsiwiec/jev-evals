import os

import pytest

from evals.bankrate_api import Offer, best_zero_point, fetch_offers, lender_in, rate_in
from evals.drivers import DRIVERS, gather, selected
from evals.report import render
from jev_evals.jev import jev_available

LOAN, PROPERTY, FICO, ZIP = 600000, 950000, 800, "96150"
START_URL = "https://www.bankrate.com/mortgages/refinance-rates/"
VALUES = {
    "loan amount": str(LOAN),
    "property value": str(PROPERTY),
    "credit score": str(FICO),
    "zip code": ZIP,
}
OBJECTIVE = (
    f"Find the best zero-point mortgage refinance rate on this page for a ${LOAN:,} loan on a ${PROPERTY:,} "
    f"property, with a {FICO} credit score, in zip code {ZIP}. Dismiss any cookie or subscription gate, enter "
    "those details in the rate search form and apply them, then filter the results to zero-point offers only "
    "(the points filter, sometimes shown as 'Points' or 'All points options'). The goal is met when the results "
    "table lists refinance offers whose points are 0 and you can read the lender name and rate of the "
    "lowest-rate offer among them."
)
RUNS = int(os.getenv("EVAL_RUNS", "1"))

pytestmark = pytest.mark.skipif(not jev_available(), reason="requires TYPESAFE_API_KEY")


def _job(name: str):
    async def run() -> dict:
        return await DRIVERS[name](START_URL, OBJECTIVE, VALUES)

    return run


def truth() -> Offer:
    best = best_zero_point(fetch_offers(LOAN, PROPERTY, FICO, ZIP))
    assert best is not None, "bankrate returned no zero-point offers"
    return best


def score(text: str, url: str, expected: Offer) -> dict:
    return {
        "expected": f"{expected.lender} @ {expected.rate}%",
        "rate_ok": rate_in(expected.rate, text),
        "lender_ok": lender_in(expected.lender, text),
        "found": bool(
            "bankrate.com" in (url or "") and rate_in(expected.rate, text) and lender_in(expected.lender, text)
        ),
    }


@pytest.mark.eval
async def test_best_zero_point_refinance_rate() -> None:
    expected = truth()
    print(f"\nground truth: {expected.lender} @ {expected.rate}% (APR {expected.apr}, {expected.points} points)")
    rows = []
    for index in range(1, RUNS + 1):
        jobs = [(name, _job(name)) for name in selected()]
        for row in await gather(jobs):
            row["run"] = index
            row.update(score(row["summary"], row["url"], expected))
            rows.append(row)
            print(render([row], "", _COLUMNS).splitlines()[3], flush=True)
    print(render(rows, f"runs={RUNS} loan={LOAN} value={PROPERTY} fico={FICO} zip={ZIP}", _COLUMNS))
    assert any(r["found"] for r in rows), f"no run reported {expected.lender} at {expected.rate}%"


_COLUMNS = [("found", "found"), ("rate ok", "rate_ok"), ("lender ok", "lender_ok"), ("expected", "expected")]

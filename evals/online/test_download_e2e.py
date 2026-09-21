import asyncio
import os
import time
from pathlib import Path

import pytest

from evals.drivers import DRIVERS, selected
from evals.report import render
from jev_evals.jev import jev_available

DOWNLOADS = Path(os.getenv("DOWNLOADS_DIR", Path.home() / "Downloads"))
START_URL = "https://freemagazines.top/?s=The+Economist+USA"
OBJECTIVE = "Download the PDF of the newest issue of The Economist USA listed on this site."
RUNS = int(os.getenv("EVAL_RUNS", "1"))
FILE_WAIT_S = 120

pytestmark = pytest.mark.skipif(not jev_available(), reason="requires TYPESAFE_API_KEY")


def _snapshot() -> set[Path]:
    return set(DOWNLOADS.glob("*.pdf"))


async def _wait_for_file(before: set[Path]) -> Path | None:
    deadline = time.perf_counter() + FILE_WAIT_S
    last = -1
    while time.perf_counter() < deadline:
        new = [p for p in _snapshot() - before if "economist" in p.name.lower()]
        if new and not list(DOWNLOADS.glob("*.crdownload")):
            size = new[0].stat().st_size
            if size == last:
                return new[0]
            last = size
        await asyncio.sleep(3)
    return None


@pytest.mark.eval
async def test_economist_download() -> None:
    rows = []
    for index in range(1, RUNS + 1):
        for name in selected():
            before = _snapshot()
            row = await DRIVERS[name](START_URL, OBJECTIVE, {})
            file = await _wait_for_file(before) if row["status"] == "done" else None
            row["run"] = index
            row["found"] = file is not None
            row["file"] = file.name if file else "-"
            if file:
                file.unlink()
            rows.append(row)
            print(render([row], "", _COLUMNS).splitlines()[3], flush=True)
            await asyncio.sleep(2)
    print(render(rows, f"runs={RUNS} downloads={DOWNLOADS}", _COLUMNS))
    assert any(r["found"] for r in rows), "no run produced a file on disk"


_COLUMNS = [("found", "found"), ("file", "file")]

import asyncio
import contextlib
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path

import httpx

from peregrine.page import HostBrowser, Tab

CHROME = os.getenv("CHROME_BINARY", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
HEADLESS = os.getenv("EVAL_HEADLESS", "1").lower() in ("1", "true", "yes")
WINDOW = os.getenv("EVAL_WINDOW", "1440,900")
OFFSCREEN = os.getenv("EVAL_WINDOW_POSITION", "-2400,0")
_START_S = 20.0


def chrome_available() -> bool:
    return Path(CHROME).exists()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.asynccontextmanager
async def fresh_chrome(headless: bool = HEADLESS):
    port, profile = _free_port(), tempfile.mkdtemp(prefix="chrome-eval-")
    flags = [
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-size={WINDOW}",
    ]
    if headless:
        flags.append("--headless=new")
    else:
        # Keep a headed window off the active desktop so it cannot steal focus.
        flags += [
            "--window-position=-2400,0",
            "--no-startup-window" if False else "--disable-features=CalculateNativeWinOcclusion",
        ]
    process = await asyncio.create_subprocess_exec(
        CHROME,
        *flags,
        "about:blank",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    endpoint = f"http://127.0.0.1:{port}"
    try:
        deadline = time.perf_counter() + _START_S
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.perf_counter() < deadline:
                with contextlib.suppress(Exception):
                    if (await client.get(f"{endpoint}/json/version")).status_code == 200:
                        break
                await asyncio.sleep(0.25)
            else:
                raise RuntimeError(f"chrome did not expose CDP at {endpoint}")
        yield endpoint
    finally:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=10)
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
        shutil.rmtree(profile, ignore_errors=True)


@contextlib.asynccontextmanager
async def open_tab(url: str, headless: bool = HEADLESS):
    async with fresh_chrome(headless) as endpoint:
        host = HostBrowser(endpoint)
        tab = Tab(host)
        try:
            await tab.open(url)
            await tab.settle()
            yield tab
        finally:
            await tab.close()
            await host.close()


async def find(tab: Tab, name: str):
    elements = (await tab.observe()).elements
    wanted = name.strip().lower()
    exact = next((e for e in elements if e.name.strip().lower() == wanted), None)
    return exact or next((e for e in elements if wanted in e.name.lower()), None)


async def wait_for_element(tab: Tab, name: str, timeout_s: float = 20.0):
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        found = await find(tab, name)
        if found is not None:
            return found
        await asyncio.sleep(0.5)
    return None

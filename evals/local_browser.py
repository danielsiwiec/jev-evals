import asyncio
import contextlib
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

import httpx

from peregrine.page import HostBrowser, Tab

CHROME = os.getenv("CHROME_BINARY", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
HEADLESS = os.getenv("EVAL_HEADLESS", "1").lower() in ("1", "true", "yes")
WINDOW = os.getenv("EVAL_WINDOW", "1440,900")
OFFSCREEN = os.getenv("EVAL_WINDOW_POSITION", "0,0")
# A headed Chrome takes focus when it launches and macOS offers no flag to stop it. Naming the app
# to put back in front restores it a moment later; the window is still visible, just not in the way.
RESTORE_FOCUS_TO = os.getenv("EVAL_RESTORE_FOCUS_TO") or os.getenv("BROWSER_KEEP_FOCUS_ON", "")
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
        # A headed window cannot be hidden on macOS: every off-screen --window-position, positive
        # or negative, is clamped back to the top-left of the desktop. Occlusion detection is
        # disabled so a covered window is not throttled, and the window is placed where it was
        # asked to go, but a headed run WILL put windows on the screen. Use EVAL_HEADLESS=1 (the
        # default) to keep the screen free.
        flags += [
            f"--window-position={OFFSCREEN}",
            "--disable-features=CalculateNativeWinOcclusion",
        ]
    process = await asyncio.create_subprocess_exec(
        CHROME,
        *flags,
        "about:blank",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    endpoint = f"http://127.0.0.1:{port}"
    await _restore_focus(headless)
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
        await _restore_focus(headless)
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
async def _restore_focus(headless: bool) -> None:
    if headless or not RESTORE_FOCUS_TO or sys.platform != "darwin":
        return
    script = f'tell application "System Events" to set frontmost of process "{RESTORE_FOCUS_TO}" to true'
    with contextlib.suppress(Exception):
        process = await asyncio.create_subprocess_exec(
            "osascript", "-e", script, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(process.wait(), timeout=5)


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

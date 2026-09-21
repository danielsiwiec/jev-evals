import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from peregrine.actions import Observation

DEFAULT_CDP_HTTP = "http://192.168.65.254:9222"
_OBSERVE_JS = (Path(__file__).parent / "observe.js").read_text()
_NAV_TIMEOUT_MS = 30_000
_ACTION_TIMEOUT_MS = 8_000
_CLICK_TIMEOUT_MS = 2_000

_SETTLE_MS = 800
_PULSE_S = 0.05
# Cheap signature of "has anything changed": document size, element count, url, and whether
# the browser still considers the document to be loading.
_DOM_PULSE_JS = """() => [
  document.readyState,
  location.href,
  document.getElementsByTagName('*').length,
  (document.body && document.body.innerHTML.length) || 0,
].join('|')"""
_OBSERVE_TIMEOUT_S = 15.0
_EVAL_TIMEOUT_S = 30.0
_SCROLL_FRACTION = 1.0
_DOWNLOAD_ERROR = re.compile(r"Download is starting", re.I)


_COMMIT_VALUE_JS = """el => {
  el.dispatchEvent(new Event('change', {bubbles: true}));
  el.blur();
}"""


def cdp_endpoint() -> str:
    return os.getenv("BROWSER_CDP_HTTP") or os.getenv("ABR_CDP_HTTP") or DEFAULT_CDP_HTTP


class BrowserUnavailable(Exception):
    pass


class HostBrowser:
    def __init__(self, cdp_http: str | None = None):
        self._cdp_http = cdp_http or cdp_endpoint()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    @property
    def endpoint(self) -> str:
        return self._cdp_http

    async def context(self) -> BrowserContext:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser.contexts[0]
            last: Exception | None = None
            for attempt in range(2):
                try:
                    if self._playwright is None:
                        self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.connect_over_cdp(self._cdp_http, timeout=20_000)
                    await self._keep_host_downloads(self._browser)
                    logger.info(f"🌐 attached to host Chrome at {self._cdp_http}")
                    return self._browser.contexts[0]
                except Exception as error:
                    last = error
                    if attempt == 0:
                        logger.warning(f"browser attach failed, restarting driver: {_short(error)}")
                        await self._reset()
            raise BrowserUnavailable(f"host Chrome unreachable at {self._cdp_http}: {last}") from last

    async def _keep_host_downloads(self, browser: Browser) -> None:
        session = await browser.new_browser_cdp_session()
        try:
            await session.send("Browser.setDownloadBehavior", {"behavior": "default", "eventsEnabled": True})
        finally:
            await session.detach()

    async def _reset(self) -> None:
        self._browser = None
        playwright, self._playwright = self._playwright, None
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass

    async def new_page(self) -> Page:
        page = await (await self.context()).new_page()
        page.set_default_timeout(_ACTION_TIMEOUT_MS)
        page.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
        await _bring_to_front(page)
        await _give_focus_back()
        return page

    async def pages(self) -> list[Page]:
        return list((await self.context()).pages)

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None


class Tab:
    def __init__(self, host: HostBrowser):
        self._host = host
        self._page: Page | None = None
        self._downloads: list[str] = []
        self._dialogs: list[str] = []
        self._watched: set[int] = set()
        self._opened: list[Page] = []
        # Which tab was in front when a new one opened, so closing returns where a person would land.
        self._opener: dict[int, Page] = {}
        self._opened_at: dict[int, float] = {}

    @property
    def page(self) -> Page | None:
        return self._page if self._page is not None and not self._page.is_closed() else None

    async def ensure(self) -> Page:
        page = self.page
        if page is None:
            page = await self._host.new_page()
            self._opened.append(page)
            self.adopt(page)
        return page

    def adopt(self, page: Page) -> None:
        self._page = page
        page.set_default_timeout(_ACTION_TIMEOUT_MS)
        page.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
        if id(page) not in self._watched:
            self._watched.add(id(page))
            page.on("download", lambda download: self._downloads.append(download.suggested_filename))
            page.on("dialog", self._on_dialog)

    async def _on_dialog(self, dialog: Any) -> None:
        # A native dialog blocks the page until it is handled, so it cannot be left open.
        # It is dismissed and reported verbatim; jev decides what to do about it next.
        self._dialogs.append(f"{dialog.type}: {dialog.message[:120]}")
        try:
            await dialog.dismiss()
        except Exception:
            pass

    def take_download(self) -> str | None:
        if not self._downloads:
            return None
        name = self._downloads[-1]
        self._downloads.clear()
        return name

    async def _siblings(self) -> list[Page]:
        return await self._host.pages()

    async def _adopt_new(self, before: list[Page]) -> str | None:
        known = {id(p) for p in before}
        opened = [p for p in await self._siblings() if id(p) not in known and not p.is_closed()]
        if not opened:
            return None
        page = opened[-1]
        previous = self.page
        if previous is not None:
            self._opener[id(page)] = previous
        self._opened_at.setdefault(id(page), time.time())
        self._opened.extend(p for p in opened if p not in self._opened)
        self.adopt(page)
        await _bring_to_front(page)
        await _give_focus_back()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        except PlaywrightError:
            pass
        await self.settle()
        # Chrome can raise itself again while the new page paints, so hand focus back once more.
        await _give_focus_back()
        return f"opened new tab {page.url}"

    async def _outcome(self, before: list[Page], default: str) -> str:
        if self.take_download():
            return "download started"
        adopted = await self._adopt_new(before)
        if self.take_download():
            return "download started"
        outcome = adopted or default
        if self._dialogs:
            outcome += " (dialog dismissed: " + "; ".join(self._dialogs) + ")"
            self._dialogs.clear()
        return outcome

    async def close(self) -> None:
        pages = [p for p in (*self._opened, self.page) if p is not None]
        self._page = None
        self._opened.clear()
        for page in dict.fromkeys(pages):
            if page.is_closed():
                continue
            try:
                await page.close()
            except Exception:
                pass

    async def open(self, url: str) -> str:
        page = await self.ensure()
        self._opened_at.setdefault(id(page), time.time())
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await _give_focus_back()
        except PlaywrightError as error:
            if _DOWNLOAD_ERROR.search(str(error)):
                return "download started"
            raise
        await self.settle()
        return "download started" if self.take_download() else "opened"

    async def settle(self, timeout_ms: int = _SETTLE_MS) -> None:
        """Return as soon as the page stops changing, rather than after a fixed wait.

        A blind sleep is wrong in both directions: too long for a page that did nothing, too short
        for one still working. This watches the DOM and returns on the first quiet interval, so a
        static page costs a few milliseconds and a busy one gets the time it needs.
        """
        page = await self.ensure()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except PlaywrightError:
            pass
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        previous = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                current = await page.evaluate(_DOM_PULSE_JS)
            except PlaywrightError:
                return
            if current == previous:
                return
            previous = current
            await asyncio.sleep(_PULSE_S)

    async def observe(self, timeout_s: float = _OBSERVE_TIMEOUT_S) -> Observation:
        page = await self.ensure()
        try:
            raw = await asyncio.wait_for(page.evaluate(_OBSERVE_JS), timeout_s)
        except TimeoutError as error:
            raise PlaywrightError(f"the page did not respond to observation within {timeout_s:.0f}s") from error
        except PlaywrightError as error:
            if "Execution context was destroyed" not in str(error) and "navigation" not in str(error).lower():
                raise
            await self.settle(_NAV_TIMEOUT_MS)
            raw = await asyncio.wait_for(page.evaluate(_OBSERVE_JS), timeout_s)
        return Observation.from_raw(raw)

    async def evaluate(self, script: str, timeout_s: float = _EVAL_TIMEOUT_S) -> Any:
        page = await self.ensure()
        try:
            return await asyncio.wait_for(page.evaluate(script), timeout_s)
        except TimeoutError as error:
            raise PlaywrightError(
                f"evaluate timed out after {timeout_s:.0f}s: the page's main thread is busy"
            ) from error

    def _locator(self, ref: int):
        assert self._page is not None
        return self._page.locator(f'[data-synthia-ref="{ref}"]').first

    async def click(self, ref: int) -> str:
        page = await self.ensure()
        before = await self._siblings()
        locator = self._locator(ref)
        try:
            await locator.scroll_into_view_if_needed(timeout=_ACTION_TIMEOUT_MS)
        except PlaywrightError:
            pass
        try:
            await locator.click(timeout=_CLICK_TIMEOUT_MS)
        except PlaywrightError as error:
            if _DOWNLOAD_ERROR.search(str(error)):
                return "download started"
            blocker = _intercepted_by(str(error))
            if blocker:
                return f"click blocked: {blocker} is on top of this element and took the click instead"
            return f"click failed: {_short(error)}"
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=_SETTLE_MS * 2)
        except PlaywrightError:
            pass
        await self.settle()
        return await self._outcome(before, "clicked")

    async def type(self, ref: int, value: str, submit: bool = False) -> str:
        await self.ensure()
        before = await self._siblings()
        locator = self._locator(ref)
        try:
            await locator.fill(value, timeout=_CLICK_TIMEOUT_MS)
            if submit:
                await locator.press("Enter")
            else:
                await locator.evaluate(_COMMIT_VALUE_JS)
        except PlaywrightError as error:
            blocker = _intercepted_by(str(error))
            if blocker:
                return f"type blocked: {blocker} is on top of this field and took the input instead"
            return f"type failed: {_short(error)}"
        await self.settle()
        outcome = await self._outcome(before, "typed")
        kept = await self._current_value(locator)
        if kept is not None and not _same_value(kept, value):
            outcome += f" (the field now reads '{kept[:40]}')"
        return outcome

    async def _current_value(self, locator: Any) -> str | None:
        try:
            return str(await locator.evaluate("el => el.value ?? el.textContent ?? ''", timeout=_ACTION_TIMEOUT_MS))
        except PlaywrightError:
            return None

    async def select(self, ref: int, value: str) -> str:
        await self.ensure()
        locator = self._locator(ref)
        try:
            await locator.select_option(label=value, timeout=_ACTION_TIMEOUT_MS)
        except PlaywrightError:
            try:
                await locator.select_option(value=value, timeout=_ACTION_TIMEOUT_MS)
            except PlaywrightError as error:
                return f"select failed: {_short(error)}"
        await self.settle()
        return "selected"

    async def press(self, key: str, ref: int | None = None) -> str:
        page = await self.ensure()
        before = await self._siblings()
        try:
            if ref is not None:
                await self._locator(ref).press(key)
            else:
                await page.keyboard.press(key)
        except PlaywrightError as error:
            return f"press failed: {_short(error)}"
        await self.settle()
        return await self._outcome(before, "pressed")

    async def scroll(self, direction: int) -> str:
        page = await self.ensure()
        await page.evaluate(f"window.scrollBy(0, {direction} * window.innerHeight * {_SCROLL_FRACTION})")
        await asyncio.sleep(0.3)
        return "scrolled"

    async def adopt_last(self) -> str:
        pages = [p for p in await self._siblings() if not p.is_closed()]
        if not pages:
            return "no tabs are open"
        self.adopt(pages[-1])
        await self.settle()
        return f"now on {pages[-1].url}"

    async def tabs(self) -> list[dict[str, Any]]:
        """Every open tab, so jev can see it left one behind rather than infer it from a title."""
        current = self.page
        now = time.time()
        listed = []
        for index, page in enumerate(await self._siblings()):
            if page.is_closed() or (page is not current and _without_fragment(page.url) == "about:blank"):
                continue
            opened = self._opened_at.get(id(page))
            listed.append(
                {
                    "index": index,
                    "url": page.url,
                    "title": await _safe_title(page),
                    "current": page is current,
                    "opened_seconds_ago": round(now - opened, 1) if opened else None,
                }
            )
        return listed

    async def close_tab(self) -> str:
        page = self.page
        if page is None:
            return "there is no tab to close"
        opener = self._opener.pop(id(page), None)
        if opener is not None and opener.is_closed():
            opener = None
        others = [
            p
            for p in await self._siblings()
            if p is not page and not p.is_closed() and _without_fragment(p.url) != "about:blank"
        ]
        target = opener or (others[-1] if others else None)
        if target is None:
            return "this tab was not opened from another one, so it was left alone"
        try:
            await page.close()
        except PlaywrightError as error:
            return f"closing the tab failed: {_short(error)}"
        self._opened = [p for p in self._opened if p is not page]
        self.adopt(target)
        await _bring_to_front(target)
        await _give_focus_back()
        await self.settle()
        return f"closed the tab and went back to {target.url}"

    async def refresh(self) -> str:
        page = await self.ensure()
        before = await self._siblings()
        try:
            await page.reload(wait_until="domcontentloaded")
        except PlaywrightError as error:
            return f"refresh failed: {_short(error)}"
        await self.settle()
        return await self._outcome(before, "reloaded")

    async def back(self) -> str:
        page = await self.ensure()
        before = page.url
        try:
            await page.go_back(wait_until="domcontentloaded")
        except PlaywrightError as error:
            return f"back failed: {_short(error)}"
        await self.settle()
        if page.url == before:
            return "there is nothing to go back to in this tab's history"
        return "went back"

    async def sleep(self, seconds: float) -> str:
        deadline = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < deadline:
            if self.take_download():
                return "download started"
            await asyncio.sleep(min(0.5, max(deadline - asyncio.get_event_loop().time(), 0)))
        await self.settle()
        return "download started" if self.take_download() else "waited"

    async def wait_for(self, text: str = "", selector: str = "", condition: str = "", timeout_s: float = 10) -> str:
        page = await self.ensure()
        timeout_ms = int(timeout_s * 1000)
        try:
            if text:
                await page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout_ms)
                return f"text {text!r} is visible"
            if selector:
                await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
                return f"selector {selector!r} is visible"
            if condition:
                await page.wait_for_function(condition, timeout=timeout_ms)
                return "condition is true"
            await asyncio.sleep(timeout_s)
            return f"waited {timeout_s}s"
        except PlaywrightError as error:
            return f"wait timed out after {timeout_s}s: {_short(error)}"

    async def screenshot(self, path: Path, full_page: bool = False) -> Path:
        page = await self.ensure()
        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path), full_page=full_page)
        return path


async def _safe_title(page: Page) -> str:
    try:
        return await page.title()
    except PlaywrightError:
        return ""


_KEEP_FOCUS_ON = os.getenv("BROWSER_KEEP_FOCUS_ON", "")


async def _give_focus_back() -> None:
    """Chrome takes the front every time a tab opens, and no flag prevents it.

    Naming an app to put back in front hands focus straight back, so a headed run can proceed
    without sitting on top of whatever the person is doing. macOS only, and a no-op unless asked.
    """
    if not _KEEP_FOCUS_ON or sys.platform != "darwin":
        return
    script = f'tell application "System Events" to set frontmost of process "{_KEEP_FOCUS_ON}" to true'
    try:
        process = await asyncio.create_subprocess_exec(
            "osascript", "-e", script, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(process.wait(), timeout=3)
    except Exception:  # noqa: BLE001 - never let cosmetics break a run
        pass


def _may_take_focus() -> bool:
    """Raising a window is only ever useful to a person watching it, and only when one run owns
    the screen. Headless has no window, parallel runs would fight over it, and a headed run parked
    off-screen is deliberately out of the way."""
    return os.getenv("BROWSER_ALLOW_FOCUS", "0").lower() in ("1", "true", "yes")


async def _bring_to_front(page: Page) -> None:
    if not _may_take_focus():
        return
    try:
        await page.bring_to_front()
    except PlaywrightError:
        pass


def _intercepted_by(message: str) -> str:
    line = next((ln for ln in message.splitlines() if "intercepts pointer events" in ln), "")
    if not line:
        return ""
    tags = re.findall(r'<([a-z0-9]+)((?:\s+[a-z-]+="[^"]*")*)', line, re.I)
    if not tags:
        return "another element"
    name, attrs = tags[-1]
    ident = re.search(r'(?:id|class)="([^"]+)"', attrs or "")
    return f"{name.lower()}.{ident.group(1).split()[0]}" if ident else name.lower()


def _same_value(actual: str, wanted: str) -> bool:
    digits = re.compile(r"[^0-9a-zA-Z]")
    return digits.sub("", actual).lower() == digits.sub("", wanted).lower()


def _without_fragment(url: str) -> str:
    return url.split("#", 1)[0]


def _short(error: BaseException) -> str:
    return str(error).splitlines()[0][:200]


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)

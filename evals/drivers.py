import asyncio
import contextlib
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from peregrine.decider import Decider, LlmDecider
from peregrine.efficiency import judge
from peregrine.jev import JevClient
from peregrine.loop import run_goal
from peregrine.models import GEMINI_MODEL, JEV_MODEL_SPEC, LUNA_MODEL
from peregrine.page import HostBrowser, Tab

CDP = os.getenv("BROWSER_CDP_HTTP", "http://localhost:9222")
MAX_STEPS = int(os.getenv("EVAL_MAX_STEPS", "40"))
TIMEOUT_S = float(os.getenv("EVAL_TIMEOUT_S", "300"))
PARALLEL = int(os.getenv("EVAL_PARALLEL", "1"))
# Judging costs about $0.00006 a run, so it is on unless explicitly turned off.
EFFICIENCY = os.getenv("EVAL_EFFICIENCY", "1").lower() in ("1", "true", "yes")
FRESH_PROFILE = os.getenv("EVAL_FRESH_PROFILE", "1").lower() in ("1", "true", "yes")
CHROME = os.getenv("CHROME_BINARY", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
_CHROME_START_S = 20.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _await_cdp(endpoint: str, deadline: float) -> None:
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.perf_counter() < deadline:
            with contextlib.suppress(Exception):
                if (await client.get(f"{endpoint}/json/version")).status_code == 200:
                    return
            await asyncio.sleep(0.25)
    raise RuntimeError(f"chrome did not expose CDP at {endpoint}")


@contextlib.asynccontextmanager
async def fresh_chrome():
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="chrome-eval-")
    process = await asyncio.create_subprocess_exec(
        CHROME,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--homepage=about:blank",
        "about:blank",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    endpoint = f"http://127.0.0.1:{port}"
    try:
        await _await_cdp(endpoint, time.perf_counter() + _CHROME_START_S)
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


def rates(model: str) -> tuple[float, float, float]:
    import litellm

    cost = litellm.model_cost.get(model) or litellm.model_cost.get(model.split("/", 1)[-1]) or {}

    def per_m(key: str) -> float:
        return float(cost.get(key) or 0) * 1_000_000

    return per_m("input_cost_per_token"), per_m("output_cost_per_token"), per_m("cache_read_input_token_cost")


async def run_driver(label: str, decider: Decider | JevClient, start_url: str, goal: str, values: dict[str, str]):
    if not FRESH_PROFILE:
        return await _drive(label, decider, CDP, start_url, goal, values)
    async with fresh_chrome() as endpoint:
        return await _drive(label, decider, endpoint, start_url, goal, values)


async def _drive(
    label: str, decider: Decider | JevClient, endpoint: str, start_url: str, goal: str, values: dict[str, str]
):
    host = HostBrowser(endpoint)
    tab = Tab(host)
    started = time.perf_counter()
    try:
        await tab.open(start_url)
        result = await run_goal(tab, decider, goal, dict(values), max_steps=MAX_STEPS, timeout_s=TIMEOUT_S)
    finally:
        await tab.close()
        await host.close()
        if isinstance(decider, JevClient):
            await decider.close()
    efficiency = (
        await judge(
            goal,
            result.narrative or result.steps,
            reached_at=result.goal_reached_at,
            values=values,
        )
        if EFFICIENCY
        else None
    )
    if efficiency is not None and result.trace_path:
        _append_efficiency(result.trace_path, goal, efficiency)
    return {
        "driver": label,
        "efficiency": efficiency.ratio if efficiency else None,
        "labels": efficiency.breakdown if efficiency else None,
        "status": result.status,
        "seconds": round(time.perf_counter() - started, 1),
        "model_calls": result.jev_calls,
        "input_tokens": result.jev_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "model_ms": result.jev_mean_ms,
        "steps": result.steps,
        "summary": result.summary,
        "url": result.url,
    }


def jev_driver():
    async def run(start_url: str, goal: str, values: dict[str, str]) -> dict[str, Any]:
        client = JevClient()
        label = f"jev ({client.model}, ${JEV_MODEL_SPEC.input_cost_per_m}/M in, output free)"
        return await run_driver(label, client, start_url, goal, values)

    return run


def llm_driver(model: str):
    async def run(start_url: str, goal: str, values: dict[str, str]) -> dict[str, Any]:
        in_rate, out_rate, cache_rate = rates(model)
        decider = LlmDecider(model, in_rate, out_rate, cache_rate)
        label = f"{model} (${in_rate}/M in, ${out_rate}/M out)"
        return await run_driver(label, decider, start_url, goal, values)

    return run


DRIVERS = {
    "jev": jev_driver(),
    "gemini": llm_driver(GEMINI_MODEL),
    "luna": llm_driver(LUNA_MODEL),
}


def _append_efficiency(trace_path: str, goal: str, efficiency) -> None:
    from peregrine.trace import Trace

    trace = Trace.__new__(Trace)
    trace.path = Path(trace_path)
    trace.shots = None
    trace.efficiency(goal, efficiency.labels, efficiency.breakdown)


async def gather(jobs: list[tuple[str, Any]], parallel: int = PARALLEL) -> list[dict[str, Any]]:
    """Run jobs with at most `parallel` in flight.

    Each job owns a throwaway Chrome, so concurrency is bounded by the machine rather than by
    anything shared. One at a time is the honest default for comparing drivers; a large batch of
    one driver is where concurrency pays.
    """
    if parallel <= 1:
        rows = []
        for _, job in jobs:
            rows.append(await job())
            await asyncio.sleep(2)
        return rows
    limit = asyncio.Semaphore(parallel)

    async def run(job):
        async with limit:
            return await job()

    return list(await asyncio.gather(*(run(job) for _, job in jobs)))


def selected() -> list[str]:
    names = [n.strip() for n in os.getenv("EVAL_DRIVERS", "jev,gemini,luna").split(",") if n.strip()]
    return [n for n in names if n in DRIVERS]

import os
import time
from typing import Any

from jev_evals.decider import Decider, LlmDecider
from jev_evals.jev import JevClient
from jev_evals.loop import run_goal
from jev_evals.models import GEMINI_MODEL, JEV_MODEL_SPEC, LUNA_MODEL
from jev_evals.page import HostBrowser, Tab

CDP = os.getenv("BROWSER_CDP_HTTP", "http://localhost:9222")
MAX_STEPS = int(os.getenv("EVAL_MAX_STEPS", "40"))
TIMEOUT_S = float(os.getenv("EVAL_TIMEOUT_S", "300"))


def rates(model: str) -> tuple[float, float, float]:
    import litellm

    cost = litellm.model_cost.get(model) or litellm.model_cost.get(model.split("/", 1)[-1]) or {}

    def per_m(key: str) -> float:
        return float(cost.get(key) or 0) * 1_000_000

    return per_m("input_cost_per_token"), per_m("output_cost_per_token"), per_m("cache_read_input_token_cost")


async def run_driver(label: str, decider: Decider | JevClient, start_url: str, goal: str, values: dict[str, str]):
    host = HostBrowser(CDP)
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
    return {
        "driver": label,
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


def selected() -> list[str]:
    names = [n.strip() for n in os.getenv("EVAL_DRIVERS", "jev,gemini,luna").split(",") if n.strip()]
    return [n for n in names if n in DRIVERS]
